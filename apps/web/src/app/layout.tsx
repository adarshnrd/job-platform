import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "react-hot-toast";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "JobPlatform AI — Your AI Career Agent",
  description: "Autonomous job discovery, matching, and application platform powered by AI.",
  icons: { icon: "/favicon.ico" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body>
        {children}
        <Toaster
          position="bottom-right"
          toastOptions={{
            style: { background: "#18181b", color: "#fafafa", border: "1px solid #3f3f46" },
            success: { iconTheme: { primary: "#f59e0b", secondary: "#000" } },
          }}
        />
      </body>
    </html>
  );
}
