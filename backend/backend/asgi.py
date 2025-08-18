"""
ASGI config for backend project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from channels.layers import get_channel_layer
import django
from django.core.asgi import get_asgi_application

# Set the Django settings module FIRST
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

# Initialize Django BEFORE importing anything else
django.setup()

# Now import channels components
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from core import routing

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": 
        URLRouter(
            routing.websocket_urlpatterns
        )
    
})
channel_layer = get_channel_layer()