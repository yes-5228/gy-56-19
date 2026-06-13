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
        was_formal = old_status in ["pending", "confirmed"]
        was_waitlist = old_status == "waitlist"
        now_cancelled = new_status == "cancelled"

        if was_formal and now_cancelled:
            released_slots = old_party_size
        elif (
            was_formal
            and new_status in ["pending", "confirmed"]
            and new_party_size < old_party_size
            and old_route == new_route
        ):
            released_slots = old_party_size - new_party_size

        if was_waitlist and new_status in ["pending", "confirmed"]:
            if new_route.is_full and new_route == old_route:
                return Response(
                    {"error": "该线路名额已满，无法从候补转为正式报名"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            serializer.validated_data["waitlist_position"] = None

        self.perform_update(serializer)

        result_message = None
        promoted_info = None

        if released_slots > 0 and old_route == new_route:
            promoted = self._process_waitlist(new_route)
            if promoted:
                promoted_details = [
                    f"{b.contact_name}({b.party_size}人)" for b in promoted
                ]
                promoted_names = ", ".join(promoted_details)
                promoted_info = {
                    "count": len(promoted),
                    "details": [
                        {"id": b.id, "name": b.contact_name, "party_size": b.party_size}
                        for b in promoted
                    ],
                }
                result_message = (
                    f"✅ 已释放 {released_slots} 个名额\n\n"
                    f"📢 以下候补用户已自动递补为正式报名(待确认)：\n"
                    f"  {promoted_names}\n\n"
                    f"他们的候补标记和序号已自动清除。"
                )
            else:
                route = new_route
                route.refresh_from_db()
                if route.has_waitlist:
                    first_wait = route.waitlist_bookings.first()
                    if first_wait and first_wait.party_size > route.available_slots:
                        result_message = (
                            f"ℹ️ 已释放 {released_slots} 个名额\n\n"
                            f"当前队首候补用户 {first_wait.contact_name} 需要 {first_wait.party_size} 人，\n"
                            f"名额不足，暂保留其候补位置等待下一轮释放。"
                        )

        if was_waitlist and new_status != "waitlist":
            self._renumber_waitlist(old_route)
            if now_cancelled:
                old_route.refresh_from_db()
                result_message = "已退出候补队列，候补序号已释放并重新编号。"
            elif new_status in ["pending", "confirmed"]:
                status_display = dict(Booking.STATUS_CHOICES).get(new_status, new_status)
                result_message = f"已从候补转为正式报名({status_display})，候补标记已清除。"

        if getattr(instance, "_prefetched_objects_cache", None):
            instance._prefetched_objects_cache = {}

        if result_message or promoted_info:
            resp_data = {**serializer.data}
            if result_message:
                resp_data["message"] = result_message
            if promoted_info:
                resp_data["promoted"] = promoted_info
            return Response(resp_data)

        return Response(serializer.data)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        route = instance.route
        old_status = instance.status
        party_size = instance.party_size
        contact_name = instance.contact_name

        self.perform_destroy(instance)

        resp = {
            "cancelled": {"name": contact_name, "status": old_status, "party_size": party_size},
        }

        if old_status in ["pending", "confirmed"]:
            status_display = dict(Booking.STATUS_CHOICES).get(old_status, old_status)
            promoted = self._process_waitlist(route)
            if promoted:
                promoted_details = [
                    f"{b.contact_name}({b.party_size}人)" for b in promoted
                ]
                promoted_names = ", ".join(promoted_details)
                resp["promoted"] = {
                    "count": len(promoted),
                    "details": [
                        {"id": b.id, "name": b.contact_name, "party_size": b.party_size}
                        for b in promoted
                    ],
                }
                resp["message"] = (
                    f"✅ 已取消【{contact_name}】的{status_display}报名（{party_size}人），释放 {party_size} 个名额\n\n"
                    f"📢 以下候补用户已自动递补为正式报名(待确认)：\n"
                    f"  {promoted_names}\n\n"
                    f"他们的候补标记和序号已自动清除，请刷新页面查看最新状态。"
                )
            else:
                route.refresh_from_db()
                extra_note = ""
                if route.has_waitlist:
                    first_wait = route.waitlist_bookings.first()
                    if first_wait and first_wait.party_size > route.available_slots:
                        extra_note = (
                            f"\n\nℹ️ 当前队首候补用户 {first_wait.contact_name} "
                            f"需要 {first_wait.party_size} 人，名额不足，\n"
                            f"暂保留其候补位置等待下一轮释放。"
                        )
                resp["message"] = (
                    f"已取消【{contact_name}】的{status_display}报名（{party_size}人），释放 {party_size} 个名额。"
                    + extra_note
                )
            return Response(resp)
        elif old_status == "waitlist":
            self._renumber_waitlist(route)
            resp["message"] = (
                f"已取消【{contact_name}】的候补报名（{party_size}人），\n"
                f"其候补位置已释放，剩余候补用户已重新编号。"
            )
            return Response(resp)

        return Response(status=status.HTTP_204_NO_CONTENT)
