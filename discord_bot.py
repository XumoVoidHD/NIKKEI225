import aiohttp
import asyncio
import credentials

# Replace this with your webhook URL
WEBHOOK_URL = credentials.WEBHOOK_URL


async def send_discord_message(content: str) -> bool:
    """
    Send a message to Discord webhook asynchronously, ensuring every message has a separator above it
    and tags @everyone, all in a single message.

    Args:
        content (str): The message to send

    Returns:
        bool: True if the message was sent successfully, False otherwise
    """
    try:
        async with aiohttp.ClientSession() as session:
            full_message = f"@everyone\n{'.' * 100}\n{content}"  # Single message

            async with session.post(WEBHOOK_URL, json={"content": full_message}) as response:
                if response.status == 204:
                    return True
                else:
                    print(f"Failed to send message. Status code: {response.status}")
                    return False

    except Exception as e:
        print(f"Error sending message: {str(e)}")
        return False
