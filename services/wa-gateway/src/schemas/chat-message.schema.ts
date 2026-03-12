import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { HydratedDocument, Types } from 'mongoose';

export type ChatMessageDocument = HydratedDocument<ChatMessage>;

export type SenderType = 'customer' | 'bot' | 'agent';
export type MessageType = 'text' | 'image' | 'document';

@Schema({ collection: 'chat_messages' })
export class ChatMessage {
  @Prop({ type: Types.ObjectId, required: true, index: true })
  session_id!: Types.ObjectId;

  @Prop({ required: true })
  sender_type!: SenderType;

  @Prop({ required: true })
  message!: string;

  @Prop({ required: true, default: () => new Date(), index: true })
  timestamp!: Date;

  @Prop({ required: true })
  message_type!: MessageType;

  @Prop()
  caption?: string;

  @Prop({ required: true, unique: true, index: true })
  wa_message_id!: string;

  @Prop({ required: true })
  wa_to!: string;

  @Prop()
  deleted_at?: Date;
}

export const ChatMessageSchema = SchemaFactory.createForClass(ChatMessage);
ChatMessageSchema.index({ session_id: 1, timestamp: -1 });
