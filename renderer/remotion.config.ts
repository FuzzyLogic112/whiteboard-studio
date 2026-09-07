import { Config } from "@remotion/cli/config";

// 容器和 CI 里通常没有 GPU，用软件渲染管线才不会黑屏
Config.setChromiumOpenGlRenderer("swangle");
Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
