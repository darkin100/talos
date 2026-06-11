// In-memory todo store.
//
// On Vercel each cold-start function instance gets its own Store, and warm
// invocations are not guaranteed to reuse the same instance — so state does
// not persist reliably across requests in production. That is acceptable
// for the Talos harness demo (the agents only care that the API responds
// 2xx); upgrade to a persistent store (e.g. Vercel KV) if real persistence
// is needed.

export class Store {
  constructor() {
    this.todos = new Map();
    this.nextId = 1;
  }

  list() {
    return [...this.todos.values()];
  }

  get(id) {
    return this.todos.get(id);
  }

  create(title) {
    const todo = {
      id: this.nextId++,
      title,
      completed: false,
      created_at: new Date().toISOString(),
    };
    this.todos.set(todo.id, todo);
    return todo;
  }

  update(id, patch) {
    const current = this.todos.get(id);
    if (!current) return null;
    // Apply all provided fields in one go — simpler than enumerating them.
    Object.assign(current, patch);
    return current;
  }

  delete(id) {
    return this.todos.delete(id);
  }

  // search returns todos whose title contains q (case-insensitive).
  // An empty query returns no results to avoid duplicating the list endpoint.
  search(q) {
    if (!q) return [];
    const needle = q.toLowerCase();
    return [...this.todos.values()].filter((t) =>
      t.title.toLowerCase().includes(needle),
    );
  }
}

export const store = new Store();
