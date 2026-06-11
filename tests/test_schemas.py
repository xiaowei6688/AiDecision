from app.schemas.chat import ClientEventType, WebSocketClientEvent


def test_websocket_client_event_validates_message_payload() -> None:
    event = WebSocketClientEvent.model_validate(
        {
            "type": "message",
            "content": "hello",
            "metadata": {"user_id": "u1"},
        }
    )

    assert event.type == ClientEventType.MESSAGE
    assert event.content == "hello"
    assert event.metadata["user_id"] == "u1"
