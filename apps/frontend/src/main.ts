import "element-plus/dist/index.css";
import "./styles.css";
import ElementPlus from "element-plus";
import { createApp } from "vue";
import App from "./App.vue";
import { i18n } from "./i18n";
import router from "./router";
createApp(App).use(ElementPlus).use(router).use(i18n).mount("#app");
