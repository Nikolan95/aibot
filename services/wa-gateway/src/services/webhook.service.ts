import { BadRequestException, Injectable, UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import crypto from 'crypto';
import { MessageType } from '../schemas/chat-message.schema';
import { InboundMessageService } from './inbound-message.service';

type IncomingRequest = {
  rawBody?: Buffer;
  signature?: string;
  body: unknown;
};

type ExtractedMessage = {
  wa_message_id: string;
  sender_phone: string;
  message_type: MessageType;
  message: string;
  caption?: string;
  wa_to: string;
};

@Injectable()
export class WebhookService {
  constructor(
    private readonly config: ConfigService,
    private readonly inbound: InboundMessageService,
  ) {}

  verify(mode?: string, token?: string, challenge?: string) {
    const verifyToken = this.config.get<string>('WA_VERIFY_TOKEN') ?? '';
    if (mode === 'subscribe' && token && token === verifyToken) return challenge ?? '';
    throw new UnauthorizedException('Webhook verification failed');
  }

  async handleIncoming(req: IncomingRequest) {
    this.validateSignatureIfConfigured(req.signature, req.rawBody);

    const extracted = this.extractMessage(req.body);
    if (!extracted) return { ok: true, ignored: true };
    return this.inbound.processIncoming(extracted);
  }

  private validateSignatureIfConfigured(signature: string | undefined, rawBody: Buffer | undefined) {
    const appSecret = this.config.get<string>('WA_APP_SECRET') ?? '';
    if (!appSecret) return;
    if (!signature || !rawBody) throw new UnauthorizedException('Missing signature');

    const expected = 'sha256=' + crypto.createHmac('sha256', appSecret).update(rawBody).digest('hex');
    const a = Buffer.from(expected);
    const b = Buffer.from(signature);
    if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
      throw new UnauthorizedException('Invalid signature');
    }
  }

  private extractMessage(body: unknown): ExtractedMessage | null {
    const payload = body as any;

    const message =
      payload?.entry?.[0]?.changes?.[0]?.value?.messages?.[0] ??
      payload?.messages?.[0] ??
      payload?.message;

    if (!message) return null;

    const wa_message_id: string | undefined = message.id ?? message.wa_message_id;
    const sender_phone: string | undefined = message.from ?? message.sender_phone ?? message.sender_id;
    const type: string | undefined = message.type ?? message.message_type;

    if (!wa_message_id || !sender_phone || !type) throw new BadRequestException('Invalid WhatsApp payload');

    const wa_to =
      payload?.entry?.[0]?.changes?.[0]?.value?.metadata?.display_phone_number ??
      payload?.entry?.[0]?.changes?.[0]?.value?.metadata?.phone_number_id ??
      payload?.wa_to ??
      '';

    if (type === 'text') {
      const text = message.text?.body ?? message.body ?? '';
      return {
        wa_message_id,
        sender_phone,
        message_type: 'text',
        message: String(text),
        wa_to,
      };
    }

    if (type === 'image') {
      const imageId = message.image?.id ?? message.media_id ?? '';
      const caption = message.image?.caption ?? message.caption ?? undefined;
      return {
        wa_message_id,
        sender_phone,
        message_type: 'image',
        message: String(imageId),
        caption,
        wa_to,
      };
    }

    if (type === 'document') {
      const docId = message.document?.id ?? message.media_id ?? '';
      const caption = message.document?.caption ?? message.caption ?? undefined;
      return {
        wa_message_id,
        sender_phone,
        message_type: 'document',
        message: String(docId),
        caption,
        wa_to,
      };
    }

    // ignore unsupported types for now (audio, video, etc.)
    return null;
  }
}
