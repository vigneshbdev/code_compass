import { createRoot } from "react-dom/client";
import { ItemList } from "./components/ItemList";

createRoot(document.getElementById("root")!).render(<ItemList items={["a", "b"]} />);
