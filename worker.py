"""Standalone scalable Python Virtual Try-On RabbitMQ Worker entrypoint."""
from app.services.rabbitmq_worker import main

if __name__ == "__main__":
    main()

