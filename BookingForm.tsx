"use client";
// src/components/BookingForm.tsx
// Shown after a customer clicks "Book this job".
// Collects contact details + preferred scheduling, calls POST /booking.

import { useState } from "react";

interface Props {
  quoteId: string;
  address: string;
  priceMin: number;
  priceMax: number;
  onSuccess: (bookingId: string, customerName: string) => void;
  onCancel: () => void;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function BookingForm({ quoteId, address, priceMin, priceMax, onSuccess, onCancel }: Props) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [date, setDate] = useState("ASAP");
  const [time, setTime] = useState("flexible");
  const [instructions, setInstructions] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!name.trim()) { setError("Please enter your name"); return; }
    if (!email.trim() && !phone.trim()) { setError("Please enter an email or phone number"); return; }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/booking`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          quote_id: quoteId,
          customer_name: name,
          customer_email: email || null,
          customer_phone: phone || null,
          preferred_date: date,
          preferred_time: time,
          special_instructions: instructions || null,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Booking failed");
      }

      const data = await res.json();
      onSuccess(data.booking_id, name);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const inputStyle = {
    width: "100%",
    padding: "11px 13px",
    fontSize: 14,
    fontFamily: "var(--font-body)",
    background: "var(--parchment)",
    border: "1.5px solid var(--fog)",
    borderRadius: "var(--radius-sm)",
    color: "var(--soil)",
    outline: "none",
  } as const;

  const labelStyle = {
    display: "flex",
    flexDirection: "column" as const,
    gap: 5,
    fontSize: 12,
    fontWeight: 600 as const,
    color: "var(--bark)",
  };

  return (
    <div
      className="animate-fade-up"
      style={{
        background: "var(--parchment)",
        borderRadius: "var(--radius-lg)",
        overflow: "hidden",
        boxShadow: "var(--shadow-float)",
        border: "1px solid var(--fog)",
      }}
    >
      {/* Header */}
      <div style={{ background: "var(--bark)", padding: "24px 28px" }}>
        <p style={{ fontSize: 12, color: "var(--sage)", fontWeight: 500, marginBottom: 6 }}>
          📍 {address}
        </p>
        <h2 style={{
          fontFamily: "var(--font-display)", fontSize: 26, color: "#f5f0e8",
          marginBottom: 4, fontStyle: "italic",
        }}>
          Book this job
        </h2>
        <p style={{ fontSize: 14, color: "rgba(255,255,255,0.7)" }}>
          Agreed quote: <strong style={{ color: "#fff" }}>${priceMin}–${priceMax} AUD</strong>
        </p>
      </div>

      {/* Form */}
      <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 16 }}>

        {/* Contact */}
        <p style={{ fontSize: 13, fontWeight: 600, color: "var(--bark)", borderBottom: "1px solid var(--fog)", paddingBottom: 8 }}>
          Your contact details
        </p>

        <label style={labelStyle}>
          Name *
          <input
            type="text" value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Your full name" style={inputStyle}
            onFocus={(e) => (e.target.style.borderColor = "var(--meadow)")}
            onBlur={(e) => (e.target.style.borderColor = "var(--fog)")}
          />
        </label>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <label style={labelStyle}>
            Email
            <input
              type="email" value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="you@email.com" style={inputStyle}
              onFocus={(e) => (e.target.style.borderColor = "var(--meadow)")}
              onBlur={(e) => (e.target.style.borderColor = "var(--fog)")}
            />
          </label>
          <label style={labelStyle}>
            Phone
            <input
              type="tel" value={phone} onChange={(e) => setPhone(e.target.value)}
              placeholder="04xx xxx xxx" style={inputStyle}
              onFocus={(e) => (e.target.style.borderColor = "var(--meadow)")}
              onBlur={(e) => (e.target.style.borderColor = "var(--fog)")}
            />
          </label>
        </div>

        {/* Scheduling */}
        <p style={{ fontSize: 13, fontWeight: 600, color: "var(--bark)", borderBottom: "1px solid var(--fog)", paddingBottom: 8, marginTop: 4 }}>
          When would you like it done?
        </p>

        {/* Date preference */}
        <label style={labelStyle}>
          Preferred date
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" as const, marginTop: 2 }}>
            {["ASAP", "This week", "Next week", "Flexible"].map((opt) => (
              <button
                key={opt} type="button"
                onClick={() => setDate(opt)}
                style={{
                  padding: "7px 14px", fontSize: 13, fontFamily: "var(--font-body)", fontWeight: 500,
                  background: date === opt ? "var(--meadow)" : "var(--parchment)",
                  border: `1.5px solid ${date === opt ? "var(--meadow)" : "var(--fog)"}`,
                  borderRadius: "var(--radius-sm)",
                  color: date === opt ? "#fff" : "var(--bark)", cursor: "pointer", transition: "all 0.15s",
                }}
              >{opt}</button>
            ))}
          </div>
        </label>

        {/* Time preference */}
        <label style={labelStyle}>
          Preferred time
          <div style={{ display: "flex", gap: 8, marginTop: 2 }}>
            {[
              { val: "morning", label: "Morning (7–12)" },
              { val: "afternoon", label: "Afternoon (12–5)" },
              { val: "flexible", label: "Flexible" },
            ].map(({ val, label }) => (
              <button
                key={val} type="button"
                onClick={() => setTime(val)}
                style={{
                  flex: 1, padding: "7px 8px", fontSize: 12, fontFamily: "var(--font-body)", fontWeight: 500,
                  background: time === val ? "var(--meadow)" : "var(--parchment)",
                  border: `1.5px solid ${time === val ? "var(--meadow)" : "var(--fog)"}`,
                  borderRadius: "var(--radius-sm)",
                  color: time === val ? "#fff" : "var(--bark)", cursor: "pointer", transition: "all 0.15s",
                }}
              >{label}</button>
            ))}
          </div>
        </label>

        {/* Special instructions */}
        <label style={labelStyle}>
          Special instructions
          <textarea
            value={instructions} onChange={(e) => setInstructions(e.target.value)}
            placeholder="e.g. call before arrival, gate code 1234, skip back garden..."
            rows={2}
            style={{ ...inputStyle, resize: "vertical" as const }}
            onFocus={(e) => (e.target.style.borderColor = "var(--meadow)")}
            onBlur={(e) => (e.target.style.borderColor = "var(--fog)")}
          />
        </label>

        {/* Error */}
        {error && (
          <div style={{ padding: "10px 14px", background: "#fff0f0", border: "1px solid #f5c6c6", borderRadius: "var(--radius-sm)", fontSize: 13, color: "#8b2020" }}>
            ⚠ {error}
          </div>
        )}

        {/* Submit */}
        <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
          <button
            type="button" onClick={handleSubmit} disabled={loading}
            style={{
              flex: 1, padding: "14px", background: "var(--meadow)", color: "#fff",
              border: "none", borderRadius: "var(--radius-md)", fontSize: 15, fontWeight: 600,
              fontFamily: "var(--font-body)", cursor: loading ? "not-allowed" : "pointer",
              opacity: loading ? 0.7 : 1, transition: "all 0.2s",
            }}
          >
            {loading ? "Sending request..." : "Confirm booking request →"}
          </button>
          <button
            type="button" onClick={onCancel}
            style={{
              padding: "14px 20px", background: "transparent", border: "1.5px solid var(--fog)",
              borderRadius: "var(--radius-md)", fontSize: 14, fontFamily: "var(--font-body)",
              color: "var(--clay)", cursor: "pointer",
            }}
          >
            Back
          </button>
        </div>

        <p style={{ fontSize: 11, color: "var(--clay)", textAlign: "center" as const }}>
          We'll contact you within 1 business day to confirm the booking.
        </p>
      </div>
    </div>
  );
}
