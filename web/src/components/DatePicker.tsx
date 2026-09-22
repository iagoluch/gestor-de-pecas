import { KeyboardEvent, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useDialogFocus } from "../hooks/useDialogFocus";

type DatePickerProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
};

type CalendarPosition = {
  left: number;
  top: number;
  width: number;
};

const WEEKDAYS = ["Do", "2ª", "3ª", "4ª", "5ª", "6ª", "Sá"];
const MONTHS = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

function parseIsoDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
  const date = new Date(year, month - 1, day, 12);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day ? date : null;
}

function parseDisplayDate(value: string): Date | null {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value.trim());
  if (!match) return null;
  const day = Number(match[1]), month = Number(match[2]), year = Number(match[3]);
  const date = new Date(year, month - 1, day, 12);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day ? date : null;
}

function isoDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function displayDate(value: string) {
  const date = parseIsoDate(value);
  if (!date) return "";
  return `${String(date.getDate()).padStart(2, "0")}/${String(date.getMonth() + 1).padStart(2, "0")}/${date.getFullYear()}`;
}

function sameDate(left: Date | null, right: Date | null) {
  return Boolean(left && right
    && left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate());
}

function monthDays(view: Date) {
  const first = new Date(view.getFullYear(), view.getMonth(), 1, 12);
  const start = new Date(first);
  start.setDate(first.getDate() - first.getDay());
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
}

function addDays(date: Date, amount: number) {
  const next = new Date(date);
  next.setDate(next.getDate() + amount);
  return next;
}

function addMonthsClamped(date: Date, amount: number) {
  const year = date.getFullYear();
  const targetMonth = date.getMonth() + amount;
  const lastDay = new Date(year, targetMonth + 1, 0, 12).getDate();
  return new Date(year, targetMonth, Math.min(date.getDate(), lastDay), 12);
}

export function DatePicker({ label, value, onChange }: DatePickerProps) {
  const selected = parseIsoDate(value);
  const today = new Date();
  const [draft, setDraft] = useState(displayDate(value));
  const [open, setOpen] = useState(false);
  const [view, setView] = useState(() => selected ?? today);
  const [focusedDate, setFocusedDate] = useState(() => selected ?? today);
  const [position, setPosition] = useState<CalendarPosition>({ left: 12, top: 12, width: 382 });
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const calendarRef = useRef<HTMLDivElement>(null);
  const calendarId = useId();

  useDialogFocus(open, calendarRef, () => setOpen(false));

  useEffect(() => {
    setDraft(displayDate(value));
    const date = parseIsoDate(value);
    if (date) {
      setView(date);
      if (!open) setFocusedDate(date);
    }
  }, [value, open]);

  useEffect(() => {
    if (!open) return undefined;
    function closeOnOutside(event: PointerEvent) {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !calendarRef.current?.contains(target)) setOpen(false);
    }
    document.addEventListener("pointerdown", closeOnOutside);
    return () => document.removeEventListener("pointerdown", closeOnOutside);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const target = calendarRef.current?.querySelector<HTMLButtonElement>(`[data-date="${isoDate(focusedDate)}"]`);
    target?.focus();
  }, [open, focusedDate, view]);

  useLayoutEffect(() => {
    if (!open) return undefined;
    function placeCalendar() {
      const rect = inputRef.current?.getBoundingClientRect();
      if (!rect) return;
      const gap = 6, edge = 12;
      const width = Math.min(382, window.innerWidth - edge * 2);
      const estimatedHeight = 390;
      const below = rect.bottom + gap;
      const top = below + estimatedHeight <= window.innerHeight ? below : Math.max(edge, rect.top - estimatedHeight - gap);
      setPosition({
        left: Math.max(edge, Math.min(rect.left, window.innerWidth - width - edge)),
        top,
        width,
      });
    }
    placeCalendar();
    window.addEventListener("resize", placeCalendar);
    window.addEventListener("scroll", placeCalendar, true);
    return () => {
      window.removeEventListener("resize", placeCalendar);
      window.removeEventListener("scroll", placeCalendar, true);
    };
  }, [open]);

  function openCalendar() {
    const target = selected ?? new Date();
    setFocusedDate(target);
    setView(target);
    setOpen(true);
  }

  function commitTypedDate() {
    const date = parseDisplayDate(draft);
    if (date) {
      onChange(isoDate(date));
      setView(date);
      setFocusedDate(date);
      return true;
    }
    setDraft(displayDate(value));
    return false;
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      if (commitTypedDate()) setOpen(false);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      openCalendar();
    }
  }

  function selectDate(date: Date) {
    onChange(isoDate(date));
    setDraft(displayDate(isoDate(date)));
    setView(date);
    setFocusedDate(date);
    setOpen(false);
  }

  function moveFocus(date: Date) {
    setFocusedDate(date);
    if (date.getMonth() !== view.getMonth() || date.getFullYear() !== view.getFullYear()) setView(date);
  }

  function handleDayKeyDown(event: KeyboardEvent<HTMLButtonElement>, date: Date) {
    let next: Date | null = null;
    if (event.key === "ArrowLeft") next = addDays(date, -1);
    else if (event.key === "ArrowRight") next = addDays(date, 1);
    else if (event.key === "ArrowUp") next = addDays(date, -7);
    else if (event.key === "ArrowDown") next = addDays(date, 7);
    else if (event.key === "Home") next = addDays(date, -date.getDay());
    else if (event.key === "End") next = addDays(date, 6 - date.getDay());
    else if (event.key === "PageUp") next = addMonthsClamped(date, -1);
    else if (event.key === "PageDown") next = addMonthsClamped(date, 1);
    else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectDate(date);
      return;
    }
    if (next) {
      event.preventDefault();
      moveFocus(next);
    }
  }

  function moveMonth(delta: number) {
    setView((current) => new Date(current.getFullYear(), current.getMonth() + delta, 1, 12));
  }

  const days = monthDays(view);

  return (
    <div className="date-picker" ref={rootRef}>
      <label className="date-picker__label" htmlFor={`${calendarId}-input`}>{label}</label>
      <input
        ref={inputRef}
        id={`${calendarId}-input`}
        className="date-picker__input"
        aria-controls={calendarId}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={label}
        inputMode="numeric"
        placeholder="dd/mm/aaaa"
        value={draft}
        onBlur={() => {
          window.setTimeout(() => {
            if (!calendarRef.current?.contains(document.activeElement)) commitTypedDate();
          }, 0);
        }}
        onChange={(event) => setDraft(event.target.value)}
        onClick={openCalendar}
        onKeyDown={handleInputKeyDown}
      />
      {open && createPortal(
        <div
          ref={calendarRef}
          id={calendarId}
          className="date-picker__calendar"
          role="dialog"
          aria-modal="true"
          aria-label={`Calendário de ${label}`}
          style={{ left: position.left, top: position.top, width: position.width }}
        >
          <header className="date-picker__header">
            <button type="button" aria-label="Mês anterior" onClick={() => moveMonth(-1)}><span aria-hidden="true">‹</span></button>
            <strong aria-live="polite">{MONTHS[view.getMonth()]} {view.getFullYear()}</strong>
            <button type="button" aria-label="Próximo mês" onClick={() => moveMonth(1)}><span aria-hidden="true">›</span></button>
          </header>
          <div className="date-picker__weekdays" aria-hidden="true">
            {WEEKDAYS.map((weekday) => <strong key={weekday}>{weekday}</strong>)}
          </div>
          <div className="date-picker__days" role="grid" aria-label={`${MONTHS[view.getMonth()]} ${view.getFullYear()}`}>
            {days.map((date) => {
              const isSelected = sameDate(date, selected);
              const outside = date.getMonth() !== view.getMonth();
              const isToday = sameDate(date, today);
              const focused = sameDate(date, focusedDate);
              return (
                <button
                  key={isoDate(date)}
                  type="button"
                  role="gridcell"
                  data-date={isoDate(date)}
                  tabIndex={focused ? 0 : -1}
                  className={[
                    "date-picker__day",
                    outside ? "date-picker__day--outside" : "",
                    isSelected ? "date-picker__day--selected" : "",
                    isToday ? "date-picker__day--today" : "",
                  ].filter(Boolean).join(" ")}
                  aria-label={date.toLocaleDateString("pt-BR", { day: "numeric", month: "long", year: "numeric" })}
                  aria-selected={isSelected}
                  aria-current={isToday ? "date" : undefined}
                  onFocus={() => setFocusedDate(date)}
                  onKeyDown={(event) => handleDayKeyDown(event, date)}
                  onClick={() => selectDate(date)}
                >
                  {date.getDate()}
                </button>
              );
            })}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
