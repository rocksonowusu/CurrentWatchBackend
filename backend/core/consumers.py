# core/consumers.py
import re
import json
from urllib.parse import parse_qs
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from .models import UserProfile
import logging

logger = logging.getLogger(__name__)

def sanitize_group_name(name):
    """Sanitize group name to only contain allowed characters"""
    # Replace invalid characters with underscores
    return re.sub(r'[^a-zA-Z0-9_\.-]', '_', name)

class DeviceStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Get channel layer
        self.channel_layer = get_channel_layer()
        
        # Parse query parameters
        query_string = self.scope['query_string'].decode()
        query_params = parse_qs(query_string)
        
        # Get email from query parameters
        email_list = query_params.get('email', [])
        if not email_list:
            logger.warning("WebSocket connection rejected: missing email")
            await self.close(code=4003)
            return
            
        self.user_email = email_list[0]
        
        # Verify user exists in UserProfile
        user = await self.get_user(self.user_email)
        if not user:
            logger.warning(f"WebSocket connection rejected: user {self.user_email} not found")
            await self.close(code=4001)
            return
            
        # Create user-specific group using user ID
        self.user_group_name = f'user_{user.id}'
        
        # Sanitize group name to ensure it only contains valid characters
        self.user_group_name = sanitize_group_name(self.user_group_name)
        
        # Join user group
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )
        
        await self.accept()
        logger.info(f"WebSocket connected for user: {self.user_email}")

    async def disconnect(self, close_code):
        # Leave user group
        if hasattr(self, 'user_group_name'):
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name
            )
        logger.info(f"WebSocket disconnected for user: {getattr(self, 'user_email', 'unknown')}, code: {close_code}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            if data.get('type') == 'heartbeat':
                await self.send(text_data=json.dumps({
                    'type': 'heartbeat_ack',
                    'timestamp': data.get('timestamp')
                }))
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")

    # Message handlers
    async def device_status(self, event):
        await self.send(text_data=json.dumps(event))

    async def command_update(self, event):
        await self.send(text_data=json.dumps(event))

    async def device_paired(self, event):
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def get_user(self, email):
        # Return the user object if exists
        try:
            return UserProfile.objects.get(email=email)
        except UserProfile.DoesNotExist:
            return None

    async def alert_notification(self, event):
        await self.send(text_data=json.dumps(event))