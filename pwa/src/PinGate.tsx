import { useState, useRef, useEffect } from "react";
import { Lock, ShieldCheck } from "lucide-react";

const VALID_PINS = ["797997", "899665"];
const STORAGE_KEY = "casaa_pin_ok";
const PIN_LENGTH = 6;

export function usePinAuth() {
  const [authed, setAuthed] = useState(() => {
    try {
      const ts = Number(localStorage.getItem(STORAGE_KEY) || "0");
      // Session valid for 7 days
      return ts > 0 && Date.now() - ts < 7 * 86400 * 1000;
    } catch {
      return false;
    }
  });

  const grant = () => {
    localStorage.setItem(STORAGE_KEY, String(Date.now()));
    setAuthed(true);
  };

  return { authed, grant };
}

export function PinGate({ onSuccess }: { onSuccess: () => void }) {
  const [digits, setDigits] = useState<string[]>(Array(PIN_LENGTH).fill(""));
  const [error, setError] = useState(false);
  const [success, setSuccess] = useState(false);
  const refs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    refs.current[0]?.focus();
  }, []);

  const handleChange = (idx: number, value: string) => {
    if (!/^\d*$/.test(value)) return;

    const next = [...digits];
    next[idx] = value.slice(-1);
    setDigits(next);
    setError(false);

    if (value && idx < PIN_LENGTH - 1) {
      refs.current[idx + 1]?.focus();
    }

    // Check if complete
    const pin = next.join("");
    if (pin.length === PIN_LENGTH && next.every((d) => d !== "")) {
      if (VALID_PINS.includes(pin)) {
        setSuccess(true);
        setTimeout(onSuccess, 400);
      } else {
        setError(true);
        setTimeout(() => {
          setDigits(Array(PIN_LENGTH).fill(""));
          refs.current[0]?.focus();
        }, 600);
      }
    }
  };

  const handleKeyDown = (idx: number, e: React.KeyboardEvent) => {
    if (e.key === "Backspace" && !digits[idx] && idx > 0) {
      refs.current[idx - 1]?.focus();
      const next = [...digits];
      next[idx - 1] = "";
      setDigits(next);
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, PIN_LENGTH);
    if (!pasted) return;
    const next = Array(PIN_LENGTH).fill("");
    for (let i = 0; i < pasted.length; i++) next[i] = pasted[i];
    setDigits(next);
    refs.current[Math.min(pasted.length, PIN_LENGTH - 1)]?.focus();

    const pin = next.join("");
    if (pin.length === PIN_LENGTH) {
      if (VALID_PINS.includes(pin)) {
        setSuccess(true);
        setTimeout(onSuccess, 400);
      } else {
        setError(true);
        setTimeout(() => {
          setDigits(Array(PIN_LENGTH).fill(""));
          refs.current[0]?.focus();
        }, 600);
      }
    }
  };

  return (
    <div className="h-screen flex flex-col items-center justify-center px-6 relative">
      <div className="bg-layer" />
      <div
        className={`glass-bright rounded-3xl p-8 w-full max-w-sm flex flex-col items-center gap-6 transition-all duration-300 ${
          error ? "animate-[shake_0.4s_ease-in-out]" : ""
        } ${success ? "scale-[0.97] opacity-80" : ""}`}
        style={{
          // @ts-expect-error -- inline keyframes
          "--tw-animate-shake": error ? "1" : "0",
        }}
      >
        <div
          className={`w-16 h-16 rounded-2xl flex items-center justify-center transition-all duration-300 ${
            success
              ? "bg-emerald-500/20 text-emerald-400"
              : error
                ? "bg-red-500/20 text-red-400"
                : "bg-indigo-500/15 text-indigo-400"
          }`}
        >
          {success ? <ShieldCheck size={28} /> : <Lock size={28} />}
        </div>

        <div className="text-center">
          <h1 className="text-xl font-bold text-slate-100 mb-1">Casaa Finance</h1>
          <p className="text-sm text-slate-400">Enter your PIN to continue</p>
        </div>

        <div className="flex gap-2.5" onPaste={handlePaste}>
          {digits.map((d, i) => (
            <input
              key={i}
              ref={(el) => { refs.current[i] = el; }}
              type="tel"
              inputMode="numeric"
              maxLength={1}
              value={d}
              onChange={(e) => handleChange(i, e.target.value)}
              onKeyDown={(e) => handleKeyDown(i, e)}
              className={`pin-digit ${
                error
                  ? "!border-red-500/60 !bg-red-500/10"
                  : success
                    ? "!border-emerald-500/60 !bg-emerald-500/10"
                    : ""
              }`}
              autoComplete="off"
            />
          ))}
        </div>

        {error && (
          <p className="text-sm text-red-400 font-medium">Incorrect PIN</p>
        )}
      </div>

      <style>{`
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          20% { transform: translateX(-8px); }
          40% { transform: translateX(8px); }
          60% { transform: translateX(-4px); }
          80% { transform: translateX(4px); }
        }
      `}</style>
    </div>
  );
}
