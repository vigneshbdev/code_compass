import { useState } from "react";

export interface ItemListProps {
  items: string[];
}

export function useSelection(initial: string | null = null) {
  const [selected, setSelected] = useState<string | null>(initial);
  return { selected, select: setSelected };
}

export const formatItem = (item: string): string => item.toUpperCase();

export function ItemList({ items }: ItemListProps) {
  const { selected, select } = useSelection();
  return (
    <ul>
      {items.map((item) => (
        <li key={item} onClick={() => select(item)} aria-selected={item === selected}>
          {formatItem(item)}
        </li>
      ))}
    </ul>
  );
}
