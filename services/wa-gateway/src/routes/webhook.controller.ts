import { Body, Controller, Get, Headers, Post, Query, Req } from '@nestjs/common';
import { WebhookService } from '../services/webhook.service';

@Controller('/webhook')
export class WebhookController {
  constructor(private readonly webhook: WebhookService) {}

  @Get()
  verify(
    @Query('hub.mode') mode: string | undefined,
    @Query('hub.verify_token') token: string | undefined,
    @Query('hub.challenge') challenge: string | undefined,
  ) {
    return this.webhook.verify(mode, token, challenge);
  }

  @Post()
  async receive(
    @Req() req: any,
    @Headers('x-hub-signature-256') signature: string | undefined,
    @Body() body: unknown,
  ) {
    return this.webhook.handleIncoming({
      rawBody: req.rawBody,
      signature,
      body,
    });
  }
}
