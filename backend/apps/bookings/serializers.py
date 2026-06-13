from rest_framework import serializers

from .models import Booking


class BookingSerializer(serializers.ModelSerializer):
    route_title = serializers.CharField(source="route.title", read_only=True)
    route_city = serializers.CharField(source="route.city", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    group_enrolled = serializers.IntegerField(source="route.enrolled_count", read_only=True)
    min_group_size = serializers.IntegerField(source="route.min_group_size", read_only=True)
    max_group_size = serializers.IntegerField(source="route.max_group_size", read_only=True)
    available_slots = serializers.IntegerField(source="route.available_slots", read_only=True)
    is_full = serializers.BooleanField(source="route.is_full", read_only=True)
    waitlist_count = serializers.IntegerField(source="route.waitlist_count", read_only=True)
    group_progress = serializers.IntegerField(source="route.group_progress", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "route",
            "route_title",
            "route_city",
            "contact_name",
            "phone",
            "party_size",
            "travel_date",
            "status",
            "status_label",
            "waitlist_position",
            "remark",
            "group_enrolled",
            "min_group_size",
            "max_group_size",
            "available_slots",
            "is_full",
            "waitlist_count",
            "group_progress",
            "created_at",
        ]
