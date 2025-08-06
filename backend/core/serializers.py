from rest_framework import serializers
from .models import UserProfile, Room, Device, DEVICE_TYPES

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['id', 'full_name', 'email', 'phone_number', 'phone_verified', 'created_at']
        read_only_fields = ['id', 'phone_verified', 'created_at']

class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ['id', 'name', 'icon', 'system', 'created_at']
        read_only_fields = ['id', 'created_at']

class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = [
            'device_id', 'name', 'type', 'room', 'system',
            'is_paired', 'pairing_code', 'endpoint_url',
            'last_seen', 'created_at', 'status', 'current_value'
        ]
        read_only_fields = [
            'is_paired', 'pairing_code', 'last_seen', 'created_at', 'current_value'
        ]

class DevicePairingSerializer(serializers.Serializer):
    email = serializers.EmailField()
    device_id = serializers.CharField()
    pairing_code = serializers.CharField()
    room_id = serializers.IntegerField(required=False)
    endpoint_url = serializers.URLField(required=False)
    device_type = serializers.ChoiceField(choices=DEVICE_TYPES, required=False)
    device_name = serializers.CharField(required=False)
    