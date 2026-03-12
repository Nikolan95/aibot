import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { MongooseModule } from '@nestjs/mongoose';
import { ChatMessage, ChatMessageSchema } from '../schemas/chat-message.schema';
import { ChatSession, ChatSessionSchema } from '../schemas/chat-session.schema';
import { HealthController } from '../routes/health.controller';
import { DevChatController } from '../routes/dev-chat.controller';
import { WebhookController } from '../routes/webhook.controller';
import { InboundMessageService } from '../services/inbound-message.service';
import { RabbitService } from '../services/rabbit.service';
import { WebhookService } from '../services/webhook.service';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    MongooseModule.forRootAsync({
      inject: [ConfigService],
      useFactory: async (config: ConfigService) => ({
        uri: config.get<string>('MONGO_URI') ?? 'mongodb://mongo:27017/aibot',
        dbName: config.get<string>('MONGO_DB') ?? 'aibot',
      }),
    }),
    MongooseModule.forFeature([
      { name: ChatSession.name, schema: ChatSessionSchema, collection: 'chat_sessions' },
      { name: ChatMessage.name, schema: ChatMessageSchema, collection: 'chat_messages' },
    ]),
  ],
  controllers: [HealthController, WebhookController, DevChatController],
  providers: [RabbitService, InboundMessageService, WebhookService],
})
export class AppModule {}
