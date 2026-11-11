import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
import aio_pika
from ..adapters.registry import ModelRegistry
from ..core.config import settings
from ..core.events import PlatformTestPingV1, TryOnGenerationRequestedV1
from .pipeline import TryOnPipeline

VTON_EXCHANGE = "vton.events"
QUEUE_GENERATION_REQUESTS = "tryon.generation.requests"


async def run_rabbitmq_worker(amqp_url: str) -> None:
    registry = ModelRegistry()
    pipeline = TryOnPipeline(registry=registry, output_dir=settings.output_dir)

    connection = await aio_pika.connect_robust(amqp_url)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=2)

        exchange = await channel.declare_exchange(VTON_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
        queue = await channel.declare_queue(
            QUEUE_GENERATION_REQUESTS,
            durable=True,
            arguments={
                "x-dead-letter-exchange": "vton.dlx",
                "x-dead-letter-routing-key": "dlq.tryon.requested",
            },
        )
        await queue.bind(exchange, routing_key="tryon.generation.requested")

        # Also listen to platform test ping for Phase 1 connectivity smoke tests
        ping_queue = await channel.declare_queue("ai.platform.test.ping", durable=True)
        await ping_queue.bind(exchange, routing_key="platform.test.ping")

        async def on_tryon_message(message: aio_pika.IncomingMessage) -> None:
            async with message.process(requeue=False):
                raw = json.loads(message.body.decode("utf-8"))
                req = TryOnGenerationRequestedV1.model_validate(raw)
                outcome = await pipeline.process_event(req)
                out_msg = aio_pika.Message(
                    body=outcome.model_dump_json().encode("utf-8"),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type="application/json",
                    correlation_id=req.correlationId,
                    message_id=outcome.eventId,
                )
                await exchange.publish(out_msg, routing_key=outcome.eventType)

        async def on_ping_message(message: aio_pika.IncomingMessage) -> None:
            async with message.process(requeue=False):
                raw = json.loads(message.body.decode("utf-8"))
                ping = PlatformTestPingV1.model_validate(raw)
                pong = {
                    "eventId": f"evt_{uuid.uuid4().hex}",
                    "eventType": "platform.test.pong",
                    "eventVersion": 1,
                    "occurredAt": datetime.now(timezone.utc).isoformat(),
                    "correlationId": ping.correlationId,
                    "source": "python-ai-worker",
                    "pingEventId": ping.eventId,
                    "modelsAvailable": len(registry.list_models()),
                }
                await exchange.publish(
                    aio_pika.Message(
                        body=json.dumps(pong).encode("utf-8"),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        content_type="application/json",
                        correlation_id=ping.correlationId,
                    ),
                    routing_key="platform.test.pong",
                )

        await queue.consume(on_tryon_message)
        await ping_queue.consume(on_ping_message)

        stop_event = asyncio.Event()
        await stop_event.wait()


def main() -> None:
    amqp_url = os.getenv("RABBITMQ_URL")
    if not amqp_url:
        raise RuntimeError("RABBITMQ_URL environment variable is required to start the AI worker.")
    asyncio.run(run_rabbitmq_worker(amqp_url))

