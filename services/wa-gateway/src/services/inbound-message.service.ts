import { Injectable } from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { Model, Types } from 'mongoose';
import { ChatCart, ChatCartDocument } from '../schemas/chat-cart.schema';
import { ChatMessage, ChatMessageDocument, MessageType } from '../schemas/chat-message.schema';
import { ChatSession, ChatSessionDocument } from '../schemas/chat-session.schema';
import { RabbitService } from './rabbit.service';

export type ExtractedMessage = {
  wa_message_id: string;
  sender_phone: string;
  message_type: MessageType;
  message: string;
  caption?: string;
  wa_to: string;
};

@Injectable()
export class InboundMessageService {
  constructor(
    private readonly rabbit: RabbitService,
    @InjectModel(ChatSession.name) private readonly sessions: Model<ChatSessionDocument>,
    @InjectModel(ChatMessage.name) private readonly messages: Model<ChatMessageDocument>,
    @InjectModel(ChatCart.name) private readonly carts: Model<ChatCartDocument>,
  ) {}

  async processIncoming(extracted: ExtractedMessage) {
    const existing = await this.messages.findOne({ wa_message_id: extracted.wa_message_id }).lean();
    if (existing) return { ok: true, ignored: true, reason: 'idempotent' };

    const now = new Date();
    const session = await this.findOrCreateSession(extracted.sender_phone, now);

    await this.messages.create({
      session_id: session._id,
      sender_type: 'customer',
      message: extracted.message,
      timestamp: now,
      message_type: extracted.message_type,
      caption: extracted.caption,
      wa_message_id: extracted.wa_message_id,
      wa_to: extracted.wa_to,
    });

    await this.rabbit.publishMessageReceived({
      session_id: String(session._id),
      wa_message_id: extracted.wa_message_id,
      sender_id: extracted.sender_phone,
      message_type: extracted.message_type,
      message: extracted.message,
      caption: extracted.caption ?? null,
      received_at: now.toISOString(),
    });

    return { ok: true };
  }

  async getHistory(senderId: string, limit: number) {
    const sender = String(senderId ?? '').trim();
    if (!sender) return { ok: false, messages: [] };

    const session = await this.sessions
      .findOne({ sender_id: sender, $or: [{ deleted_at: { $exists: false } }, { deleted_at: null }] })
      .lean();

    if (!session?._id) return { ok: true, messages: [] };

    const sessionId = new Types.ObjectId(String(session._id));
    const messages = await this.messages
      .find({ session_id: sessionId })
      .sort({ timestamp: 1 })
      .limit(Math.max(1, Math.min(limit, 200)))
      .lean();

    return {
      ok: true,
      session_id: String(sessionId),
      messages: messages.map((m) => ({
        sender_type: m.sender_type,
        message: m.message,
        message_type: m.message_type,
        timestamp: m.timestamp,
        intent: (m as any).intent ?? null,
        intent_confidence: (m as any).intent_confidence ?? null,
      })),
    };
  }

  async getCart(senderId: string) {
    const sender = String(senderId ?? '').trim();
    if (!sender) return { ok: false, items: [] };

    const session = await this.sessions
      .findOne({ sender_id: sender, $or: [{ deleted_at: { $exists: false } }, { deleted_at: null }] })
      .lean();

    if (!session?._id) return { ok: true, items: [] };
    const sessionId = new Types.ObjectId(String(session._id));

    const cart = await this.carts.findOne({ session_id: sessionId, status: { $in: ['active', null] } }).lean();
    const items = (cart?.items ?? []) as Array<Record<string, unknown>>;

    return { ok: true, items };
  }

  private async findOrCreateSession(senderPhone: string, now: Date): Promise<ChatSessionDocument> {
    const existing = await this.sessions.findOne({
      sender_id: senderPhone,
      $or: [{ deleted_at: { $exists: false } }, { deleted_at: null }],
    });
    if (!existing) {
      return this.sessions.create({
        sender_id: senderPhone,
        unread_count: 1,
        active: true,
        last_message_at: now,
        session_data: {},
      });
    }

    await this.sessions.updateOne(
      { _id: existing._id },
      { $inc: { unread_count: 1 }, $set: { last_message_at: now, active: true } },
    );

    return existing;
  }
}
