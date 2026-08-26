import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SOMPO Rural Risk Command Center",
  description: "Inteligência operacional de risco rural SOMPO",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="pt-BR"><body>{children}</body></html>;
}
