import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { HydratedDocument } from 'mongoose';

export type ChatSessionDocument = HydratedDocument<ChatSession>;

@Schema({ collection: 'chat_sessions' })
export class ChatSession {
  @Prop({ required: true, index: true })
  sender_id!: string;

  @Prop({ required: true, default: 0 })
  unread_count!: number;

  @Prop({ required: true, default: true })
  active!: boolean;

  @Prop({ required: true, default: () => new Date() })
  last_message_at!: Date;

  @Prop()
  assigned_agent_id?: string;

  @Prop()
  vin?: string;

  @Prop({ type: Object, default: {} })
  session_data!: Record<string, unknown>;

  @Prop()
  deleted_at?: Date;
}

export const ChatSessionSchema = SchemaFactory.createForClass(ChatSession);
ChatSessionSchema.index({ sender_id: 1, deleted_at: 1 });
