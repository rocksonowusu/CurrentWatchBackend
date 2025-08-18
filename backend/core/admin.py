from django.contrib import admin
from .models import UserProfile, Room, Device, Controller, DeviceCommand, DeviceAlert, ActivityLog
from django.utils.html import format_html
import qrcode
from io import BytesIO
import base64
from django.utils.safestring import mark_safe
from django.utils import timezone

class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('email', 'full_name', 'phone_number', 'phone_verified', 'room_count', 'device_count', 'controller_count', 'created_at')
    list_filter = ('phone_verified', 'created_at')
    search_fields = ('email', 'full_name', 'phone_number')
    readonly_fields = ('created_at',)
    
    def room_count(self, obj):
        return obj.rooms.count()
    room_count.short_description = 'Rooms'
    
    def device_count(self, obj):
        return obj.devices.filter(is_paired=True).count()
    device_count.short_description = 'Paired Devices'
    
    def controller_count(self, obj):
        return obj.controllers.count()
    controller_count.short_description = 'Controllers'

class DeviceInline(admin.TabularInline):
    model = Device
    extra = 0
    fields = ('device_id', 'name', 'hardware_pin', 'type', 'is_paired', 'status', 'pairing_code')
    readonly_fields = ('device_id', 'pairing_code', 'hardware_pin')  # Make hardware_pin readonly
    
    def get_readonly_fields(self, request, obj=None):
        # If device is paired, make hardware_pin readonly to prevent breaking communication
        if obj and hasattr(obj, 'is_paired') and obj.is_paired:
            return self.readonly_fields + ('hardware_pin',)
        return self.readonly_fields

class ControllerInline(admin.TabularInline):
    model = Controller
    extra = 0
    fields = ('controller_id', 'name', 'is_online', 'last_seen', 'ip_address')
    readonly_fields = ('controller_id', 'last_seen')

class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'icon', 'device_count', 'controller_count', 'created_at')
    list_filter = ('owner', 'created_at')
    search_fields = ('name', 'owner__email')
    readonly_fields = ('created_at',)
    inlines = [DeviceInline, ControllerInline]
    
    def device_count(self, obj):
        return obj.devices.count()
    device_count.short_description = 'Devices'
    
    def controller_count(self, obj):
        return obj.controllers.count()
    controller_count.short_description = 'Controllers'

class DeviceCommandInline(admin.TabularInline):
    model = DeviceCommand
    extra = 0
    fields = ('device_info', 'action', 'created_at', 'executed_at', 'is_executed')
    readonly_fields = ('device_info', 'created_at', 'executed_at')
    
    def device_info(self, obj):
        if obj.device:
            return f"{obj.device.name} ({obj.device.hardware_pin})"
        return "System Command"
    device_info.short_description = 'Device (Hardware Pin)'

class DeviceAlertInline(admin.TabularInline):
    model = DeviceAlert
    extra = 0
    fields = ('alert_type', 'message', 'created_at', 'is_resolved')
    readonly_fields = ('created_at',)

class ControllerAdmin(admin.ModelAdmin):
    list_display = ('controller_id', 'name', 'owner', 'room', 'is_online', 'device_count', 'pending_commands', 'last_seen', 'ip_address')
    list_filter = ('is_online', 'owner', 'room', 'created_at')
    search_fields = ('controller_id', 'name', 'owner__email', 'ip_address')
    readonly_fields = ('created_at', 'last_seen')
    inlines = [DeviceInline, DeviceCommandInline, DeviceAlertInline]
    actions = ['mark_online', 'mark_offline', 'clear_pending_commands']
    
    fieldsets = (
        ('Controller Information', {
            'fields': ('controller_id', 'name', 'ip_address')
        }),
        ('Ownership & Location', {
            'fields': ('owner', 'room')
        }),
        ('Status', {
            'fields': ('is_online', 'last_seen')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def device_count(self, obj):
        return obj.devices.count()
    device_count.short_description = 'Devices'
    
    def pending_commands(self, obj):
        count = obj.commands.filter(is_executed=False).count()
        if count > 0:
            return format_html('<span style="color: orange; font-weight: bold;">{}</span>', count)
        return count
    pending_commands.short_description = 'Pending Commands'
    
    def mark_online(self, request, queryset):
        count = queryset.update(is_online=True, last_seen=timezone.now())
        self.message_user(request, f"Marked {count} controllers as online")
    mark_online.short_description = "Mark selected controllers as online"
    
    def mark_offline(self, request, queryset):
        count = queryset.update(is_online=False)
        self.message_user(request, f"Marked {count} controllers as offline")
    mark_offline.short_description = "Mark selected controllers as offline"
    
    def clear_pending_commands(self, request, queryset):
        total_cleared = 0
        for controller in queryset:
            cleared = controller.commands.filter(is_executed=False).update(is_executed=True, executed_at=timezone.now())
            total_cleared += cleared
        self.message_user(request, f"Cleared {total_cleared} pending commands")
    clear_pending_commands.short_description = "Clear pending commands for selected controllers"

class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        'device_id', 'name', 'hardware_pin_display', 'type', 'owner', 'room', 
        'controller', 'is_paired', 'status', 'current_display', 'pairing_code', 
        'qr_code_preview', 'last_seen'
    )
    list_filter = ('type', 'is_paired', 'status', 'owner', 'room', 'controller', 'created_at')
    search_fields = ('device_id', 'name', 'pairing_code', 'owner__email', 'hardware_pin')
    readonly_fields = ('qr_code_preview', 'created_at', 'last_seen', 'device_info_summary')
    actions = ['generate_pairing_codes', 'unpair_devices', 'pair_devices', 'turn_on_devices', 'turn_off_devices']
    inlines = [DeviceCommandInline, DeviceAlertInline]
    
    fieldsets = (
        ('Device Information', {
            'fields': ('device_id', 'name', 'type', 'device_info_summary')
        }),
        ('Hardware Configuration', {
            'fields': ('hardware_pin',),
            'description': 'WARNING: Do not change hardware_pin after pairing as it breaks ESP32 communication!'
        }),
        ('Controller & Location', {
            'fields': ('controller', 'owner', 'room')
        }),
        ('Pairing & Status', {
            'fields': ('is_paired', 'pairing_code', 'qr_code_preview', 'endpoint_url', 'status', 'current_value')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'last_seen'),
            'classes': ('collapse',)
        }),
    )

    def device_info_summary(self, obj):
        """Show a summary of device naming vs hardware pin"""
        return format_html(
            '<strong>User sees:</strong> {} <br>'
            '<strong>ESP32 uses:</strong> {} <br>'
            '<strong>Device ID:</strong> {}',
            obj.name, obj.hardware_pin or 'Not set', obj.device_id
        )
    device_info_summary.short_description = 'Device Name Summary'

    def hardware_pin_display(self, obj):
        """Display hardware pin with warning if missing"""
        if obj.hardware_pin:
            return format_html('<code>{}</code>', obj.hardware_pin)
        return format_html('<span style="color: red;">⚠️ Missing</span>')
    hardware_pin_display.short_description = 'Hardware Pin'

    def current_display(self, obj):
        if obj.current_value is not None:
            if obj.current_value > 5:  # Alert for high current
                return format_html('<span style="color: red; font-weight: bold;">{:.2f}A</span>', obj.current_value)
            return f"{obj.current_value:.2f}A"
        return "-"
    current_display.short_description = 'Current'

    def qr_code_preview(self, obj):
        if obj.pairing_code:
            # Generate QR code on the fly for display
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=4,
                border=2,
            )
            qr_data = f"device_id:{obj.device_id}|pairing_code:{obj.pairing_code}"
            qr.add_data(qr_data)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            img_b64 = base64.b64encode(buffer.getvalue()).decode()
            
            return format_html(
                '<img src="data:image/png;base64,{}" width="100" height="100" />',
                img_b64
            )
        return "No pairing code generated"
    qr_code_preview.short_description = 'QR Code'

    def generate_pairing_codes(self, request, queryset):
        count = 0
        for device in queryset:
            if not device.pairing_code:
                device.generate_pairing_code()
                count += 1
        self.message_user(request, f"Generated pairing codes for {count} devices")
    generate_pairing_codes.short_description = "Generate Pairing Codes"

    def unpair_devices(self, request, queryset):
        count = 0
        for device in queryset.filter(is_paired=True):
            device.is_paired = False
            device.owner = None
            device.room = None
            device.endpoint_url = ''
            device.generate_pairing_code()  # Generate new pairing code
            device.save()
            count += 1
        self.message_user(request, f"Unpaired {count} devices and generated new pairing codes")
    unpair_devices.short_description = "Unpair Selected Devices"

    def pair_devices(self, request, queryset):
        count = 0
        for device in queryset.filter(is_paired=False):
            if device.owner:  # Only pair if there's an owner set
                device.is_paired = True
                device.save()
                count += 1
        self.message_user(request, f"Paired {count} devices (devices must have owner assigned)")
    pair_devices.short_description = "Pair Selected Devices (if owner assigned)"
    
    def turn_on_devices(self, request, queryset):
        count = 0
        for device in queryset.filter(is_paired=True):
            if device.controller:
                DeviceCommand.objects.create(
                    device=device,
                    controller=device.controller,
                    action='on'
                )
                count += 1
        self.message_user(request, f"Created 'turn on' commands for {count} devices")
    turn_on_devices.short_description = "Send Turn On command to selected devices"
    
    def turn_off_devices(self, request, queryset):
        count = 0
        for device in queryset.filter(is_paired=True):
            if device.controller:
                DeviceCommand.objects.create(
                    device=device,
                    controller=device.controller,
                    action='off'
                )
                count += 1
        self.message_user(request, f"Created 'turn off' commands for {count} devices")
    turn_off_devices.short_description = "Send Turn Off command to selected devices"

    def save_model(self, request, obj, form, change):
        if not obj.pairing_code:
            obj.generate_pairing_code()
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(self.readonly_fields)
        # Make hardware_pin readonly if device is paired to prevent breaking communication
        if obj and obj.is_paired:
            readonly_fields.append('hardware_pin')
        return readonly_fields

    def get_queryset(self, request):
        # Optimize queries by selecting related objects
        return super().get_queryset(request).select_related('owner', 'room', 'controller')

class DeviceCommandAdmin(admin.ModelAdmin):
    list_display = ('id', 'device_display', 'controller', 'action', 'created_at', 'executed_at', 'is_executed', 'execution_time')
    list_filter = ('action', 'is_executed', 'created_at', 'controller')
    search_fields = ('device__name', 'device__device_id', 'controller__controller_id', 'device__hardware_pin')
    readonly_fields = ('created_at', 'executed_at', 'execution_time')
    actions = ['mark_executed', 'mark_pending']
    
    def device_display(self, obj):
        if obj.device:
            return format_html('{} <br><small>Pin: <code>{}</code></small>', 
                             obj.device.name, obj.device.hardware_pin or 'Unknown')
        return 'System Command'
    device_display.short_description = 'Device (Hardware Pin)'
    
    def execution_time(self, obj):
        if obj.executed_at and obj.created_at:
            delta = obj.executed_at - obj.created_at
            return f"{delta.total_seconds():.1f}s"
        return "-"
    execution_time.short_description = 'Exec Time'
    
    def mark_executed(self, request, queryset):
        count = queryset.filter(is_executed=False).update(
            is_executed=True, 
            executed_at=timezone.now()
        )
        self.message_user(request, f"Marked {count} commands as executed")
    mark_executed.short_description = "Mark selected commands as executed"
    
    def mark_pending(self, request, queryset):
        count = queryset.filter(is_executed=True).update(
            is_executed=False, 
            executed_at=None
        )
        self.message_user(request, f"Marked {count} commands as pending")
    mark_pending.short_description = "Mark selected commands as pending"

class DeviceAlertAdmin(admin.ModelAdmin):
    list_display = ('id', 'device_display', 'controller', 'alert_type', 'message_preview', 'created_at', 'is_resolved')
    list_filter = ('alert_type', 'is_resolved', 'created_at', 'controller')
    search_fields = ('device__name', 'device__device_id', 'controller__controller_id', 'message')
    readonly_fields = ('created_at',)
    actions = ['mark_resolved', 'mark_unresolved']
    
    def device_display(self, obj):
        if obj.device:
            return format_html('{} <br><small>Pin: <code>{}</code></small>', 
                             obj.device.name, obj.device.hardware_pin or 'Unknown')
        return 'Unknown Device'
    device_display.short_description = 'Device (Hardware Pin)'
    
    def message_preview(self, obj):
        return obj.message[:50] + "..." if len(obj.message) > 50 else obj.message
    message_preview.short_description = 'Message'
    
    def mark_resolved(self, request, queryset):
        count = queryset.update(is_resolved=True)
        self.message_user(request, f"Marked {count} alerts as resolved")
    mark_resolved.short_description = "Mark selected alerts as resolved"
    
    def mark_unresolved(self, request, queryset):
        count = queryset.update(is_resolved=False)
        self.message_user(request, f"Marked {count} alerts as unresolved")
    mark_unresolved.short_description = "Mark selected alerts as unresolved"


# --- ACTIVITY LOG ---
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'log_type', 'action_type', 'user', 'device', 'controller', 'room', 'message')
    list_filter = ('log_type', 'action_type', 'created_at', 'source')
    search_fields = ('message', 'details', 'user__email', 'device__name', 'controller__controller_id')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    list_select_related = ('user', 'device', 'controller', 'room')

# Register models with admin
admin.site.register(UserProfile, UserProfileAdmin)
admin.site.register(Room, RoomAdmin)
admin.site.register(Controller, ControllerAdmin)
admin.site.register(Device, DeviceAdmin)
admin.site.register(DeviceCommand, DeviceCommandAdmin)
admin.site.register(DeviceAlert, DeviceAlertAdmin)
admin.site.register(ActivityLog, ActivityLogAdmin)

# Customize admin site header and title
admin.site.site_header = "CurrentWatch Smart Home Admin"
admin.site.site_title = "CurrentWatch Admin Portal"
admin.site.index_title = "Welcome to CurrentWatch Smart Home Administration"