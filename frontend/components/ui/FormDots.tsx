interface Props {
  form: string; // e.g. "WWDLW"
}

const colorMap: Record<string, string> = {
  W: "bg-win",
  D: "bg-draw",
  L: "bg-loss",
};

const labelMap: Record<string, string> = {
  W: "V",
  D: "E",
  L: "D",
};

export default function FormDots({ form }: Props) {
  return (
    <div className="flex items-center gap-1">
      {form.split("").map((ch, i) => (
        <span
          key={i}
          className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold text-white ${colorMap[ch] ?? "bg-draw"}`}
        >
          {labelMap[ch] ?? ch}
        </span>
      ))}
    </div>
  );
}
