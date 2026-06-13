<template>
  <section class="booking-layout">
    <form class="booking-form" @submit.prevent="submit">
      <div>
        <p class="eyebrow">Registration</p>
        <h3>新增报名</h3>
      </div>
      <label>
        选择线路
        <select v-model.number="form.route" required>
          <option disabled value="">请选择</option>
          <option v-for="route in routesWithStats" :key="route.id" :value="route.id">
            {{ route.title }}
            <span v-if="route.is_full">（已满，候补 {{ route.waitlist_count }} 人）</span>
            <span v-else>（剩余 {{ route.available_slots }} 名额）</span>
          </option>
        </select>
      </label>
      <div v-if="selectedRoute && selectedRoute.is_full" class="alert alert-info">
        ⚠️ 该线路名额已满，提交后将进入候补队列，按提交顺序等待空位
      </div>
      <label>
        联系人
        <input v-model="form.contact_name" required />
      </label>
      <label>
        手机号
        <input v-model="form.phone" required />
      </label>
      <div class="form-row">
        <label>
          人数
          <input v-model.number="form.party_size" min="1" type="number" required />
        </label>
        <label>
          出行日期
          <input v-model="form.travel_date" type="date" required />
        </label>
      </div>
      <label>
        备注
        <textarea v-model="form.remark" rows="3"></textarea>
      </label>
      <button class="primary-action" type="submit">
        {{ selectedRoute && selectedRoute.is_full ? '候补报名' : '提交报名' }}
      </button>
    </form>

    <section class="table-panel">
      <div class="panel-head">
        <div>
          <p class="eyebrow">Group Status</p>
          <h3>报名与成团状态</h3>
        </div>
        <span>{{ bookings.length }} 条报名</span>
      </div>
      <div class="booking-list">
        <article v-for="booking in sortedBookings" :key="booking.id" :class="{ 'waitlist-item': booking.status === 'waitlist' }">
          <div>
            <h4>
              {{ booking.contact_name }} · {{ booking.party_size }} 人
              <span v-if="booking.status === 'waitlist'" class="waitlist-badge">
                候补第 {{ booking.waitlist_position }} 位
              </span>
            </h4>
            <p>{{ booking.route_title }} / {{ booking.travel_date }}</p>
            <p class="stats">
              已报名 {{ booking.group_enrolled }}/{{ booking.max_group_size }} 人
              <span v-if="booking.waitlist_count > 0"> · 候补 {{ booking.waitlist_count }} 人</span>
            </p>
          </div>
          <span :class="['tag', `tag-${booking.status}`]">{{ booking.status_label }}</span>
          <div class="action-col">
            <strong>{{ booking.group_enrolled }}/{{ booking.min_group_size }}</strong>
            <button
              v-if="booking.status !== 'cancelled'"
              class="text-btn"
              type="button"
              @click="cancelBooking(booking.id)"
            >
              取消
            </button>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, reactive } from "vue";

const props = defineProps({
  routes: { type: Array, required: true },
  bookings: { type: Array, required: true },
});

const emit = defineEmits(["booking-created", "booking-cancelled"]);

const form = reactive({
  route: "",
  contact_name: "",
  phone: "",
  party_size: 1,
  travel_date: "",
  status: "pending",
  remark: "",
});

const routesWithStats = computed(() => {
  return props.routes.map(route => {
    const routeBookings = props.bookings.filter(b => b.route === route.id);
    const enrolled = routeBookings
      .filter(b => ["pending", "confirmed"].includes(b.status))
      .reduce((sum, b) => sum + b.party_size, 0);
    const waitlistCount = routeBookings
      .filter(b => b.status === "waitlist")
      .reduce((sum, b) => sum + b.party_size, 0);
    return {
      ...route,
      enrolled_count: enrolled,
      available_slots: Math.max(0, route.max_group_size - enrolled),
      is_full: enrolled >= route.max_group_size,
      waitlist_count: waitlistCount,
    };
  });
});

const selectedRoute = computed(() => {
  if (!form.route) return null;
  return routesWithStats.value.find(r => r.id === form.route);
});

const sortedBookings = computed(() => {
  return [...props.bookings].sort((a, b) => {
    const statusOrder = { waitlist: 0, pending: 1, confirmed: 2, cancelled: 3 };
    if (statusOrder[a.status] !== statusOrder[b.status]) {
      return statusOrder[a.status] - statusOrder[b.status];
    }
    if (a.status === "waitlist") {
      return (a.waitlist_position || 0) - (b.waitlist_position || 0);
    }
    return new Date(b.created_at) - new Date(a.created_at);
  });
});

function submit() {
  emit("booking-created", { ...form });
  form.contact_name = "";
  form.phone = "";
  form.party_size = 1;
  form.travel_date = "";
  form.remark = "";
}

function cancelBooking(id) {
  if (confirm("确定要取消该报名吗？取消后将释放名额给候补用户。")) {
    emit("booking-cancelled", id);
  }
}
</script>
