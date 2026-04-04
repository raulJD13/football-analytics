"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";

interface Props {
  title: string;
  value: number | string;
  suffix?: string;
  decimals?: number;
}

export default function KpiCard({ title, value, suffix, decimals = 0 }: Props) {
  const numericValue = typeof value === "number" ? value : null;
  const [display, setDisplay] = useState(numericValue !== null ? 0 : value);
  const ref = useRef<number | null>(null);

  useEffect(() => {
    if (numericValue === null) {
      setDisplay(value);
      return;
    }
    const duration = 800;
    const start = performance.now();
    const from = 0;
    const to = numericValue;

    function tick(now: number) {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(Number((from + (to - from) * eased).toFixed(decimals)));
      if (t < 1) ref.current = requestAnimationFrame(tick);
    }
    ref.current = requestAnimationFrame(tick);
    return () => {
      if (ref.current) cancelAnimationFrame(ref.current);
    };
  }, [numericValue, value, decimals]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="rounded-lg border border-border-custom bg-bg-card p-5 transition-transform duration-150 hover:-translate-y-px"
    >
      <p className="text-xs font-medium text-text-secondary">{title}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-text-primary">
        {display}
        {suffix && (
          <span className="ml-0.5 text-sm font-normal text-text-secondary">
            {suffix}
          </span>
        )}
      </p>
    </motion.div>
  );
}
