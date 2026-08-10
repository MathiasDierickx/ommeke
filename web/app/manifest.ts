import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Lusmaker",
    short_name: "Ommeke",
    description: "Bouw, bewaar en download persoonlijke fiets- en traillussen.",
    start_url: "/",
    display: "standalone",
    background_color: "#f3f0e8",
    theme_color: "#183f30",
    orientation: "portrait-primary",
    icons: [
      {
        src: "/favicon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "maskable",
      },
      {
        src: "/apple-touch-icon.png",
        sizes: "180x180",
        type: "image/png",
      },
    ],
  };
}
