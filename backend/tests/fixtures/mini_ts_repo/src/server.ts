import express from "express";

const app = express();
const router = express.Router();

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

router.post("/items", (req, res) => {
  res.status(201).json(req.body);
});

app.use("/api", router);

export function start(port: number): void {
  app.listen(port);
}
