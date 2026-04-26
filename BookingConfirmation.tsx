"use client";
// src/components/BookingConfirmation.tsx

interface Props {
  bookingId: string;
  customerName: string;
  address: string;
  onReset: () => void;
}

export default function BookingConfirmation({ bookingId, customerName, address, onReset }: Props) {
  return (
    <div
      className="animate-fade-up"
      style={{
        background: "var(--parchment)",
        borderRadius: "var(--radius-lg)",
        overflow: "hidden",
        boxShadow: "var(--shadow-float)",
        border: "1px solid var(--fog)",
        textAlign: "center",
      }}
    >
      {/* Success banner */}
      <div style={{
        background: "var(--meadow)",
        padding: "36px 28px",
        position: "relative",
        overflow: "hidden",
      }}>
        <div style={{
          position: "absolute", inset: 0,
          backgroundImage: "radial-gradient(circle at 70% 30%, rgba(255,255,255,0.08) 0%, transparent 60%)",
          pointerEvents: "none",
        }} />
        <div style={{
          width: 64, height: 64, borderRadius: "50%",
          background: "rgba(255,255,255,0.2)",
          display: "flex", alignItems: "center", justifyContent: "center",
          margin: "0 auto 16px",
          fontSize: 30,
        }}>
          ✓
        </div>
        <h2 style={{
          fontFamily: "var(--font-display)", fontSize: 28, color: "#fff",
          marginBottom: 8, fontStyle: "italic",
        }}>
          Booking request received!
        </h2>
        <p style={{ fontSize: 14, color: "rgba(255,255,255,0.8)" }}>
          Thanks {customerName} — we'll be in touch within 1 business day.
        </p>
      </div>

      {/* Details */}
      <div style={{ padding: "28px", display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{
          padding: "16px", background: "var(--mist)",
          borderRadius: "var(--radius-md)", border: "1px solid var(--fog)",
          textAlign: "left",
        }}>
          <p style={{ fontSize: 12, color: "var(--clay)", marginBottom: 8 }}>Booking details</p>
          <p style={{ fontSize: 14, color: "var(--bark)", marginBottom: 4 }}>
            📍 {address}
          </p>
          <p style={{ fontSize: 12, color: "var(--clay)" }}>
            Reference: <code style={{ fontFamily: "monospace", background: "var(--fog)", padding: "1px 5px", borderRadius: 3 }}>
              {bookingId.slice(0, 8).toUpperCase()}
            </code>
          </p>
        </div>

        <div style={{
          padding: "14px", background: "rgba(61,107,53,0.06)",
          borderRadius: "var(--radius-sm)", border: "1px solid rgba(61,107,53,0.15)",
        }}>
          <p style={{ fontSize: 13, color: "var(--meadow)", fontWeight: 500 }}>
            What happens next?
          </p>
          <p style={{ fontSize: 12, color: "var(--clay)", marginTop: 6, lineHeight: 1.6 }}>
            Our team will review your booking and confirm a time that works.
            We may call or email to discuss access, confirm the scope, and lock in the date.
          </p>
        </div>

        <button
          type="button" onClick={onReset}
          style={{
            width: "100%", padding: "13px",
            background: "transparent", border: "1.5px solid var(--fog)",
            borderRadius: "var(--radius-md)", fontSize: 14, fontFamily: "var(--font-body)",
            color: "var(--clay)", cursor: "pointer", marginTop: 4,
          }}
        >
          Get another quote
        </button>
      </div>
    </div>
  );
}
