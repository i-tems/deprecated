import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "모임 스케줄러",
  description: "교대근무, 일반근무, 프리랜서 — 다 달라도 약속은 잡을 수 있어요",
  icons: {
    icon: "/favicon.svg",
  },
  openGraph: {
    title: "모임 스케줄러",
    description: "교대근무, 일반근무, 프리랜서 — 다 달라도 약속은 잡을 수 있어요",
    url: "https://meetup.i-tems.com",
    siteName: "모임 스케줄러",
    images: [
      {
        url: "https://meetup.i-tems.com/og-image.png",
        width: 1200,
        height: 630,
        alt: "모임 스케줄러",
      },
    ],
    type: "website",
    locale: "ko_KR",
  },
  twitter: {
    card: "summary_large_image",
    title: "모임 스케줄러",
    description: "교대근무, 일반근무, 프리랜서 — 다 달라도 약속은 잡을 수 있어요",
    images: ["https://meetup.i-tems.com/og-image.png"],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <head>
        <script dangerouslySetInnerHTML={{ __html: `
          (function() {
            var ua = navigator.userAgent || '';
            if (/KAKAOTALK/i.test(ua)) {
              location.href = 'kakaotalk://web/openExternal?url=' + encodeURIComponent(location.href);
            }
          })();
        `}} />
      </head>
      <body className="min-h-dvh">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
