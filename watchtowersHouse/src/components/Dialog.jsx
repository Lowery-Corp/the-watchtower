import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export default function Dialog({
  children,
  className = "",
  dismissible = true,
  initialFocusSelector,
  label,
  labelledBy,
  onClose,
}) {
  const dialogRef = useRef(null);
  const closeRef = useRef(onClose);
  const dismissibleRef = useRef(dismissible);

  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => { dismissibleRef.current = dismissible; }, [dismissible]);

  useEffect(() => {
    const dialog = dialogRef.current;
    const previousFocus = document.activeElement;
    const appRoot = document.getElementById("root");
    const previousOverflow = document.body.style.overflow;
    const previousAriaHidden = appRoot?.getAttribute("aria-hidden");
    const previousInert = appRoot?.inert;

    document.body.style.overflow = "hidden";
    if (appRoot) {
      appRoot.setAttribute("aria-hidden", "true");
      appRoot.inert = true;
    }

    const initialFocus = initialFocusSelector
      ? dialog?.querySelector(initialFocusSelector)
      : dialog?.querySelector(FOCUSABLE);
    initialFocus?.focus();

    const handleKeyDown = (event) => {
      if (event.key === "Escape" && dismissibleRef.current) {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = [...dialog.querySelectorAll(FOCUSABLE)];
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      if (appRoot) {
        if (previousAriaHidden === null) appRoot.removeAttribute("aria-hidden");
        else appRoot.setAttribute("aria-hidden", previousAriaHidden);
        appRoot.inert = previousInert;
      }
      previousFocus?.focus();
    };
  }, [initialFocusSelector]);

  return createPortal(
    <div className="modal-backdrop" role="presentation">
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        aria-labelledby={labelledBy}
        className={`modal-card ${className}`}
        tabIndex={-1}
      >
        {children}
      </section>
    </div>,
    document.body,
  );
}
