"use client";
/** WAI-ARIA tabs: arrow keys move between tabs, Home/End jump, the panel is focusable. */
import { useRef } from "react";
import styles from "./visitor.module.css";

export interface TabDef {
  id: string;
  label: string;
}

export function tabId(id: string): string {
  return `visitor-tab-${id}`;
}

export function panelId(id: string): string {
  return `visitor-panel-${id}`;
}

export default function Tabs({
  tabs,
  active,
  onChange,
  label,
}: {
  tabs: TabDef[];
  active: string;
  onChange: (id: string) => void;
  label: string;
}) {
  const listRef = useRef<HTMLDivElement | null>(null);

  const move = (delta: number) => {
    const index = tabs.findIndex((tab) => tab.id === active);
    const next = tabs[(index + delta + tabs.length) % tabs.length];
    onChange(next.id);
    listRef.current?.querySelector<HTMLButtonElement>(`#${tabId(next.id)}`)?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        move(1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        move(-1);
        break;
      case "Home":
        event.preventDefault();
        onChange(tabs[0].id);
        listRef.current?.querySelector<HTMLButtonElement>(`#${tabId(tabs[0].id)}`)?.focus();
        break;
      case "End": {
        event.preventDefault();
        const last = tabs[tabs.length - 1];
        onChange(last.id);
        listRef.current?.querySelector<HTMLButtonElement>(`#${tabId(last.id)}`)?.focus();
        break;
      }
      default:
        break;
    }
  };

  return (
    <div className={styles.tablist} role="tablist" aria-label={label} ref={listRef} onKeyDown={onKeyDown}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={tabId(tab.id)}
          className={styles.tab}
          aria-selected={tab.id === active}
          aria-controls={panelId(tab.id)}
          tabIndex={tab.id === active ? 0 : -1}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
