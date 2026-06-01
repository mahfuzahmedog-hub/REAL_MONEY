import type { Metadata } from "next"
import "./globals.css"

export const metadata: Metadata = {
  title: "REAL MONEY — AI Video Shorts",
  description: "Turn long videos into viral shorts with AI",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
