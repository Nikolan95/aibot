import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { HydratedDocument, Types } from 'mongoose';

export type ChatCartDocument = HydratedDocument<ChatCart>;

@Schema({ collection: 'chat_carts' })
export class ChatCart {
  @Prop({ type: Types.ObjectId, required: true, index: true })
  session_id!: Types.ObjectId;

  @Prop({ required: true, index: true })
  cart_id!: string;

  @Prop({ required: true, index: true })
  sender_id!: string;

  @Prop({ required: true, default: 'active', index: true })
  status!: 'active' | 'checked_out';

  @Prop()
  checked_out_at?: Date;

  @Prop({ type: Array, default: [] })
  items!: Array<Record<string, unknown>>;

  @Prop({ required: true, default: () => new Date() })
  created_at!: Date;

  @Prop({ required: true, default: () => new Date() })
  updated_at!: Date;
}

export const ChatCartSchema = SchemaFactory.createForClass(ChatCart);
ChatCartSchema.index({ sender_id: 1 });
ChatCartSchema.index({ session_id: 1, status: 1 });
ChatCartSchema.index({ cart_id: 1 }, { unique: true });
