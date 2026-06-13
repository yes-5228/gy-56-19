from django.db import models, transaction
from rest_framework import viewsets, status
from rest_framework.response import Response

from .models import Booking
from .serializers import BookingSerializer


class BookingViewSet(viewsets.ModelViewSet):
    serializer_class = BookingSerializer

    def get_queryset(self):
        queryset = Booking.objects.select_related("route").all()
        route_id = self.request.query_params.get("route")
        status = self.request.query_params.get("status")
        if route_id:
            queryset = queryset.filter(route_id=route_id)
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def _get_next_waitlist_position(self, route):
        max_position = route.bookings.filter(status="waitlist").aggregate(
            models.Max("waitlist_position")
        )["waitlist_position__max"]
        return (max_position or 0) + 1

    def _process_waitlist(self, route):
        if not route.has_waitlist:
            return []

        promoted = []
        waitlist_bookings = list(route.waitlist_bookings)
        remaining_slots = route.available_slots

        for booking in waitlist_bookings:
            if remaining_slots <= 0:
                break
            if booking.party_size > remaining_slots:
                break
            booking.status = "pending"
            booking.waitlist_position = None
            booking.save()
            promoted.append(booking)
            remaining_slots -= booking.party_size

        self._renumber_waitlist(route)
        return promoted

    def _renumber_waitlist(self, route):
        waitlist_bookings = route.bookings.filter(status="waitlist").order_by(
            "waitlist_position", "created_at"
        )
        for idx, booking in enumerate(waitlist_bookings, start=1):
            if booking.waitlist_position != idx:
                booking.waitlist_position = idx
                booking.save(update_fields=["waitlist_position"])

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        route = serializer.validated_data["route"]
        party_size = serializer.validated_data["party_size"]

        if route.is_full:
            next_position = self._get_next_waitlist_position(route)
            serializer.save(status="waitlist", waitlist_position=next_position)
            headers = self.get_success_headers(serializer.data)
            return Response(
                {
                    **serializer.data,
                    "message": f"名额已满，已加入候补队列，当前候补第 {next_position} 位",
                },
                status=status.HTTP_201_CREATED,
                headers=headers,
            )

        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        old_status = instance.status
        old_party_size = instance.party_size
        old_route = instance.route

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data.get("status", old_status)
        new_party_size = serializer.validated_data.get("party_size", old_party_size)
        new_route = serializer.validated_data.get("route", old_route)

        released_slots = 0
        if old_status in ["pending", "confirmed"] and new_status == "cancelled":
            released_slots = old_party_size
        elif (
            old_status in ["pending", "confirmed"]
            and new_status in ["pending", "confirmed"]
            and new_party_size < old_party_size
            and old_route == new_route
        ):
            released_slots = old_party_size - new_party_size

        if old_status == "waitlist" and new_status in ["pending", "confirmed"]:
            if new_route.is_full and new_route == old_route:
                return Response(
                    {"error": "该线路名额已满，无法从候补转为正式报名"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            serializer.validated_data["waitlist_position"] = None

        self.perform_update(serializer)

        if released_slots > 0 and old_route == new_route:
            promoted = self._process_waitlist(new_route)
            if promoted:
                promoted_names = ", ".join(b.contact_name for b in promoted)
                return Response(
                    {
                        **serializer.data,
                        "message": f"已释放 {released_slots} 个名额，候补用户 {promoted_names} 已自动递补",
                        "promoted_count": len(promoted),
                    }
                )

        if old_status == "waitlist" and new_status != "waitlist":
            self._renumber_waitlist(old_route)

        if getattr(instance, "_prefetched_objects_cache", None):
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        route = instance.route
        old_status = instance.status
        party_size = instance.party_size

        self.perform_destroy(instance)

        if old_status in ["pending", "confirmed"]:
            promoted = self._process_waitlist(route)
            if promoted:
                promoted_names = ", ".join(b.contact_name for b in promoted)
                return Response(
                    {
                        "message": f"预订已删除，已释放 {party_size} 个名额，候补用户 {promoted_names} 已自动递补",
                        "promoted_count": len(promoted),
                    }
                )
        elif old_status == "waitlist":
            self._renumber_waitlist(route)

        return Response(status=status.HTTP_204_NO_CONTENT)
