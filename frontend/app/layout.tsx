import type { Metadata } from "next";
import { Inter, Geist_Mono } from "next/font/google";
import Sidebar from "@/components/layout/Sidebar";
import Topbar from "@/components/layout/Topbar";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Football Analytics",
  description: "LaLiga match prediction and analytics dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-bg-main text-text-primary">
        <Sidebar />
        <div className="ml-[188px] flex min-h-screen flex-col">
          <Topbar />
          <main className="flex-1 p-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
