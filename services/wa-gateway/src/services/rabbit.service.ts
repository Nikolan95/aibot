import { Injectable, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import amqp = require('amqplib');
import type { Channel, ChannelModel, ConsumeMessage } from 'amqplib';
import crypto = require('crypto');
import { InjectModel } from '@nestjs/mongoose';
import { Model, Types } from 'mongoose';
import { ChatMessage, ChatMessageDocument } from '../schemas/chat-message.schema';
import { ChatSession, ChatSessionDocument } from '../schemas/chat-session.schema';

export type SendRequest = {
  session_id: string;
  wa_to: string;
  message: string;
};

@Injectable()
export class RabbitService implements OnModuleInit, OnModuleDestroy {
  private conn?: ChannelModel;
  private channel?: Channel;

  constructor(
    private readonly config: ConfigService,
    @InjectModel(ChatSession.name) private readonly sessions: Model<ChatSessionDocument>,
    @InjectModel(ChatMessage.name) private readonly messages: Model<ChatMessageDocument>,
  ) {}

  async onModuleInit() {
    const url = this.config.get<string>('RABBITMQ_URL') ?? 'amqp://guest:guest@rabbitmq:5672/';
    const conn = await amqp.connect(url);
    const channel = await conn.createChannel();

    this.conn = conn;
    this.channel = channel;

    await channel.assertQueue('message_received', { durable: true });
    await channel.assertQueue('wa_send', { durable: true });

    await channel.consume('wa_send', (msg) => this.handleOutbound(msg), { noAck: false });
  }

  async onModuleDestroy() {
    await this.channel?.close().catch(() => undefined);
    await this.conn?.close().catch(() => undefined);
  }

  async publishMessageReceived(payload: unknown) {
    if (!this.channel) throw new Error('Rabbit channel not ready');
    this.channel.sendToQueue('message_received', Buffer.from(JSON.stringify(payload)), { persistent: true });
  }

  private async handleOutbound(msg: ConsumeMessage | null) {
    if (!msg || !this.channel) return;
    try {
      const body = JSON.parse(msg.content.toString('utf-8')) as SendRequest;

      const waMessageId = await this.sendViaMetaOrFake(body.wa_to, body.message);

      const sessionObjectId = new Types.ObjectId(body.session_id);
      await this.messages.create({
        session_id: sessionObjectId,
        sender_type: 'bot',
        message: body.message,
        timestamp: new Date(),
        message_type: 'text',
        wa_to: body.wa_to,
        wa_message_id: waMessageId,
      });

      await this.sessions.updateOne(
        { _id: sessionObjectId },
        { $set: { last_message_at: new Date() } },
      );

      this.channel.ack(msg);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('wa_send error', err);
      this.channel.nack(msg, false, false);
    }
  }

  private async sendViaMetaOrFake(_to: string, _text: string): Promise<string> {
    const accessToken = this.config.get<string>('WA_ACCESS_TOKEN') ?? '';
    const phoneNumberId = this.config.get<string>('WA_PHONE_NUMBER_ID') ?? '';

    if (!accessToken || !phoneNumberId) {
      return `wamid.fake.${crypto.randomBytes(8).toString('hex')}`;
    }

    // Network calls are intentionally omitted here to keep local dev self-contained.
    // Plug Meta Cloud API send here later (Graph API).
    return `wamid.todo.${crypto.randomBytes(8).toString('hex')}`;
  }
}
