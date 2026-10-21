<script setup lang="ts">
import { ref, computed, onUnmounted } from "vue";
import { ArrowRight, Lock, User } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";
import { supabase, loadProfile } from "../composables/useAuth";
import BrandLogo from "../components/BrandLogo.vue";

const router = useRouter();
const email = ref("");
const password = ref("");
const token = ref("");
const sentEmail = ref("");
const signup = ref(false);
const error = ref("");
const notice = ref("");
const loading = ref(false);
const resendAt = ref(0);
const now = ref(Date.now());
const secondsLeft = computed(() =>
  Math.max(0, Math.ceil((resendAt.value - now.value) / 1000)),
);
const timer = window.setInterval(() => {
  now.value = Date.now();
}, 1000);
onUnmounted(() => window.clearInterval(timer));

function message(cause: unknown) {
  const code = (cause as { code?: string })?.code;
  return (
    (
      {
        invalid_credentials: "邮箱或密码不正确。",
        email_not_confirmed: "邮箱尚未验证，请切换到注册并重新发送验证码。",
        otp_expired: "验证码错误或已过期。",
        over_email_send_rate_limit: "发送过于频繁，请稍后再试。",
        over_request_rate_limit: "操作过于频繁，请稍后再试。",
      } as Record<string, string>
    )[code || ""] ||
    (cause instanceof Error ? cause.message : "登录失败，请稍后重试。")
  );
}
async function enter() {
  await loadProfile();
  await router.push("/");
}
async function resend() {
  if (loading.value || secondsLeft.value > 0) return;
  loading.value = true;
  error.value = "";
  try {
    const { error: cause } = await (
      await supabase()
    ).auth.resend({
      email: sentEmail.value || email.value.trim(),
      type: "signup",
    });
    if (cause) throw cause;
    sentEmail.value ||= email.value.trim();
    resendAt.value = Date.now() + 60_000;
    notice.value = "验证码已发送，请查看邮箱。";
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loading.value = false;
  }
}
async function login() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  notice.value = "";
  try {
    const client = await supabase();
    if (!signup.value) {
      const { error: cause } = await client.auth.signInWithPassword({
        email: email.value.trim(),
        password: password.value,
      });
      if (cause) throw cause;
      await enter();
    } else if (sentEmail.value) {
      if (!/^\d{6}$/.test(token.value))
        throw new Error("请输入 6 位数字验证码。");
      const { error: cause } = await client.auth.verifyOtp({
        email: sentEmail.value,
        token: token.value,
        type: "signup",
      });
      if (cause) throw cause;
      await enter();
    } else {
      if (secondsLeft.value > 0) return;
      const { data, error: cause } = await client.auth.signUp({
        email: email.value.trim(),
        password: password.value,
      });
      if (cause) throw cause;
      if (data.user?.identities?.length === 0)
        throw new Error("该邮箱已注册，请直接使用 Antler 账号登录。");
      password.value = "";
      if (data.session) {
        await enter();
        return;
      }
      sentEmail.value = email.value.trim();
      resendAt.value = Date.now() + 60_000;
      notice.value = "验证码已发送，请查看邮箱。";
    }
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loading.value = false;
  }
}
function switchMode() {
  signup.value = !signup.value;
  sentEmail.value =
    token.value =
    password.value =
    error.value =
    notice.value =
      "";
}
</script>

<template>
  <main class="login-page">
    <header class="login-top-brand">
      <BrandLogo class="brand-mark" /><strong>ANTLER</strong><i>/</i
      ><span>Knowledge Core</span>
    </header>
    <section class="login-card">
      <div class="login-heading">
        <BrandLogo class="heading-mark" />
        <h1>{{ signup ? "注册 Antler 账号" : "登录 Antler 控制台" }}</h1>
        <span>与 Antler 共用邮箱和密码</span>
      </div>
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        show-icon
        :closable="false"
        class="login-alert"
      />
      <el-form class="login-form" label-position="top" @submit.prevent="login">
        <el-form-item label="邮箱"
          ><el-input
            v-model="email"
            type="email"
            :disabled="loading || !!sentEmail"
            required
            autocomplete="email"
            placeholder="you@example.com"
            size="large"
            ><template #prefix
              ><el-icon><User /></el-icon></template></el-input
        ></el-form-item>
        <el-form-item v-if="!sentEmail" label="密码"
          ><el-input
            v-model="password"
            type="password"
            show-password
            required
            :minlength="signup ? 6 : undefined"
            :disabled="loading"
            :autocomplete="signup ? 'new-password' : 'current-password'"
            placeholder="请输入登录密码"
            size="large"
            ><template #prefix
              ><el-icon><Lock /></el-icon></template></el-input
        ></el-form-item>
        <el-form-item v-if="sentEmail" label="邮箱验证码">
          <el-input
            v-model="token"
            inputmode="numeric"
            maxlength="6"
            autocomplete="one-time-code"
            required
            :disabled="loading"
          />
        </el-form-item>
        <p v-if="notice" role="status">{{ notice }}</p>
        <el-button
          type="primary"
          native-type="submit"
          :loading="loading"
          class="login-submit-btn mb-2"
          >{{
            loading
              ? "请稍候"
              : !signup
                ? "登录控制台"
                : sentEmail
                  ? "验证并完成注册"
                  : "注册并发送验证码"
          }}
          <el-icon class="ml-1"><ArrowRight /></el-icon
        ></el-button>
      </el-form>
      <div v-if="signup" class="session-row mb-2">
        <button
          type="button"
          :disabled="loading || secondsLeft > 0"
          @click="resend"
        >
          {{
            secondsLeft > 0
              ? `${secondsLeft} 秒后可重发`
              : "已有验证码？重新发送"
          }}
        </button>
        <button
          v-if="sentEmail"
          type="button"
          :disabled="loading"
          @click="
            sentEmail = '';
            token = '';
            notice = '';
          "
        >
          更换邮箱
        </button>
      </div>
      <el-button text class="px-0" :disabled="loading" @click="switchMode" >{{
        signup ? "已有账号？登录" : "没有账号？注册"
      }}</el-button>
    </section>
    <footer class="login-footer">
      <span>© 2025 Antler Knowledge RAG · v2.4.0</span>
      <div>
        <a href="#">开发文档</a><a href="#">安全规范</a><a href="#">系统状态</a>
      </div>
    </footer>
  </main>
</template>

<style scoped>
.login-page {
  position: relative;
  display: grid;
  min-height: 100vh;
  width: 100vw;
  overflow: hidden;
  place-items: center;
  background:
    radial-gradient(
      circle at 50% 0%,
      rgba(137, 206, 255, 0.22),
      transparent 32%
    ),
    radial-gradient(#dae2fd 1px, transparent 1px), #faf8ff;
  background-size:
    auto,
    24px 24px,
    auto;
}
.login-top-brand {
  position: absolute;
  top: 48px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #3f4850;
  font-family: "JetBrains Mono", monospace;
  font-size: 14px;
}
.login-top-brand strong {
  color: #131b2e;
  font-family: "Geist", sans-serif;
  font-size: 16px;
}
.login-top-brand i {
  color: #707881;
  font-style: normal;
}
.brand-mark {
  width: 36px;
  height: 36px;
}
.login-card {
  position: relative;
  z-index: 1;
  width: min(480px, calc(100vw - 32px));
  padding: 36px 56px;
  background: #fff;
  border: 1px solid rgba(191, 199, 210, 0.4);
  border-radius: 12px;
  box-shadow: 0 12px 28px rgba(19, 27, 46, 0.11);
  animation: fadeIn 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}
.login-heading {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 0 0 28px;
  text-align: center;
}
.heading-mark {
  width: 64px;
  height: 64px;
  margin-bottom: 10px;
}
.login-heading h1 {
  margin: 0 0 5px;
  color: #131b2e;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.login-heading span {
  color: #3f4850;
  font-size: 12px;
}
.login-alert {
  margin-bottom: 16px;
}
.login-form :deep(.el-form-item) {
  margin-bottom: 16px;
}
.login-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  color: #131b2e;
  font-size: 15px;
  font-weight: 600;
}
.login-submit-btn {
  width: 100%;
  height: 42px;
  margin-top: 4px;
  background: #006194 !important;
  border-radius: 7px;
  font-weight: 700;
}
.ml-1 {
  margin-left: 4px;
}
.session-row {
  display: flex;
  justify-content: space-between;
  color: #3f4850;
  font-size: 12px;
}
.session-row label {
  display: flex;
  align-items: center;
  gap: 5px;
}
.session-row input {
  width: 16px;
  height: 16px;
  accent-color: #006194;
}
.session-row span {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #707881;
  font-family: "JetBrains Mono", monospace;
  font-size: 11px;
}
.session-row i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #006194;
}
.login-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 22px 0 16px;
  color: #707881;
  font-family: "JetBrains Mono", monospace;
  font-size: 10px;
}
.login-divider::before,
.login-divider::after {
  flex: 1;
  height: 1px;
  background: #d8dee7;
  content: "";
}
.sso-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.sso-row button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 34px;
  color: #3f4850;
  background: #f2f3ff;
  border: 1px solid #d8dee7;
  border-radius: 7px;
  cursor: pointer;
  font-size: 12px;
}
.login-footer {
  position: absolute;
  bottom: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: min(1024px, calc(100vw - 48px));
  color: #707881;
  font-family: "JetBrains Mono", monospace;
  font-size: 10px;
}
.login-footer div {
  display: flex;
  gap: 16px;
}
.login-footer a {
  color: inherit;
  text-decoration: none;
}
@media (max-width: 480px) {
  .login-card {
    padding: 30px 24px;
  }
  .login-top-brand {
    top: 22px;
  }
  .login-footer {
    bottom: 20px;
    width: calc(100vw - 32px);
  }
  .login-footer div {
    display: none;
  }
}
</style>
