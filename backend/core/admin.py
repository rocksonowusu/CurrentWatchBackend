from django.contrib import admin
from .models import UserProfile, Room, Device
from django.utils.html import format_html
import qrcode
from io import BytesIO
import base64
from django.utils.safestring import mark_safe

class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('email', 'full_name', 'phone_number', 'phone_verified', 'room_count', 'device_count', 'created_at')
    list_filter = ('phone_verified', 'created_at')
    search_fields = ('email', 'full_name', 'phone_number')
    readonly_fields = ('created_at',)
    
    def room_count(self, obj):
        return obj.rooms.count()
    room_count.short_description = 'Rooms'
    
    def device_count(self, obj):
        return obj.devices.filter(is_paired=True).count()
    device_count.short_description = 'Paired Devices'

class DeviceInline(admin.TabularInline):
    model = Device
    extra = 0
    fields = ('device_id', 'name', 'type', 'is_paired', 'pairing_code')
    readonly_fields = ('device_id', 'pairing_code')

class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'icon', 'device_count', 'created_at')
    list_filter = ('owner', 'created_at')
    search_fields = ('name', 'owner__email')
    readonly_fields = ('created_at',)
    inlines = [DeviceInline]
    
    def device_count(self, obj):
        return obj.devices.count()
    device_count.short_description = 'Devices'

class DeviceAdmin(admin.ModelAdmin):
    list_display = ('device_id', 'name', 'type', 'owner', 'room', 'is_paired', 'status', 'current_value', 'pairing_code', 'qr_code_preview', 'last_seen')
    list_filter = ('type', 'is_paired', 'status', 'current_value', 'owner', 'room', 'created_at')
    search_fields = ('device_id', 'name', 'pairing_code', 'owner__email')
    readonly_fields = ('qr_code_preview', 'created_at', 'last_seen')
    actions = ['generate_pairing_codes', 'unpair_devices', 'pair_devices']
    
    fieldsets = (
        ('Device Information', {
            'fields': ('device_id', 'name', 'type')
        }),
        ('Ownership & Location', {
            'fields': ('owner', 'room')
        }),
        ('Pairing Status', {
            'fields': ('is_paired', 'pairing_code', 'qr_code_preview', 'endpoint_url')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'last_seen'),
            'classes': ('collapse',)
        }),
    )

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

    def save_model(self, request, obj, form, change):
        if not obj.pairing_code:
            obj.generate_pairing_code()
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        # Optimize queries by selecting related objects
        return super().get_queryset(request).select_related('owner', 'room')

# Register models with admin
admin.site.register(UserProfile, UserProfileAdmin)
admin.site.register(Room, RoomAdmin)
admin.site.register(Device, DeviceAdmin)

# Customize admin site header and title
admin.site.site_header = "CurrentWatch Smart Home Admin"
admin.site.site_title = "CurrentWatch Admin Portal"
admin.site.index_title = "Welcome to CurrentWatch, Smart Home Administration"