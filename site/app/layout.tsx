import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Paper Atlas — Make every paper legible',
  description: 'A visual research workspace for turning papers into connected concept maps.',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
