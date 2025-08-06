from django.urls import path
from .views import (
    OnboardingStartView,
    PhoneVerificationView,
    RoomCreationView,
    DevicePairingInitView,
    DevicePairingCompleteView,
    DeviceStatusView,
    DeviceListView
)

urlpatterns = [
    # User Onboarding
    path('onboarding/start/', OnboardingStartView.as_view(), name='onboarding-start'),
    path('onboarding/phone/', PhoneVerificationView.as_view(), name='phone-verification'),
    
    # Room Management
    path('rooms/create/', RoomCreationView.as_view(), name='room-create'),
    
    # Device Management
    path('devices/list/', DeviceListView.as_view(), name='device-list'),
    path('devices/pairing/init/', DevicePairingInitView.as_view(), name='device-pairing-init'),
    path('devices/pairing/complete/', DevicePairingCompleteView.as_view(), name='device-pairing-complete'),
    path('devices/status/', DeviceStatusView.as_view(), name='device-status'),
]