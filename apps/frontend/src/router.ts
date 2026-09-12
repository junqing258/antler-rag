import { createRouter, createWebHashHistory } from "vue-router";
import LoginPage from "./routes/LoginPage.vue";
import AdminLayout from "./layouts/AdminLayout.vue";
import DashboardPage from "./routes/DashboardPage.vue";
import KnowledgeBasesPage from "./routes/KnowledgeBasesPage.vue";
import RetrievalPage from "./routes/RetrievalPage.vue";
import MembersPage from "./routes/MembersPage.vue";
import ApiKeysPage from "./routes/ApiKeysPage.vue";
import { authState } from "./composables/useAuth";

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/login", component: LoginPage },
    {
      path: "/",
      component: AdminLayout,
      children: [
        { path: "", component: DashboardPage },
        { path: "knowledge-bases", component: KnowledgeBasesPage },
        { path: "retrieve", component: RetrievalPage },
        { path: "members", component: MembersPage },
        { path: "api-keys", component: ApiKeysPage },
      ],
    },
  ],
});
router.beforeEach((to) => {
  if (to.path !== "/login" && !authState.token) return "/login";
  if (to.path === "/login" && authState.token) return "/";
});
export default router;
