from django.urls import path
from .views import (
    DeviceCommandExecutedView,
    DeviceCommandStatusView,
    OnboardingStartView,
    PhoneVerificationView,
    RoomCreationView,
    ControllerRegistrationView,
    DevicePairingInitView,
    DevicePairingCompleteView,
    DeviceControlView,
    DeviceCommandsView,
    DeviceStatusView,
    DeviceAlertsView,
    DeviceListView,
    ActivityLogListView,
    AlertDismissalView,
    DeviceManagementView,
    UserProfileUpdateView,
    EmergencyControlsView,
    SystemSettingsView
)

urlpatterns = [
    # User Onboarding
    path('onboarding/start/', OnboardingStartView.as_view(), name='onboarding-start'),
    path('onboarding/phone/', PhoneVerificationView.as_view(), name='phone-verification'),
    
    # Room Management
    path('rooms/create/', RoomCreationView.as_view(), name='room-create'),
    
    # Controller Management
    path('devices/controller/register/', ControllerRegistrationView.as_view(), name='controller-register'),
    path('devices/commands/', DeviceCommandsView.as_view(), name='device-commands'),
    path('devices/alerts/', DeviceAlertsView.as_view(), name='device-alerts'),
    path('devices/commands/executed/', DeviceCommandExecutedView.as_view(), name='device_command_executed'),
    path('devices/commands/<int:command_id>/status/', DeviceCommandStatusView.as_view(), name='command-status'),
    
    
    # Device Management
    path('devices/list/', DeviceListView.as_view(), name='device-list'),
    path('devices/control/', DeviceControlView.as_view(), name='device-control'),
    path('devices/pairing/init/', DevicePairingInitView.as_view(), name='device-pairing-init'),
    path('devices/pairing/complete/', DevicePairingCompleteView.as_view(), name='device-pairing-complete'),
    path('devices/status/', DeviceStatusView.as_view(), name='device-status'),
    path('logs/', ActivityLogListView.as_view(), name='activity_logs'),

    # Settings related endpoints
    path('profile/', UserProfileUpdateView.as_view(), name='user-profile'),
    path('devices/<str:device_id>/remove/', DeviceManagementView.as_view(), name='remove-device'),
    path('system/settings/', SystemSettingsView.as_view(), name='system-settings'),
    path('system/emergency/', EmergencyControlsView.as_view(), name='emergency-controls'),
    path('alerts/dismiss/', AlertDismissalView.as_view(), name='dismiss-alert'),
]
