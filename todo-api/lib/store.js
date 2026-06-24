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

  update(id, title, completed) {
    const existing = this.todos.get(id);
    if (!existing) return null;
    existing.title = title;
    // Only update completed if explicitly provided (not undefined)
    if (completed !== undefined) {
      existing.completed = !!completed;
    }
    return existing;
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

  // deleteCompleted deletes all completed todos and returns the count deleted.
  deleteCompleted() {
    const beforeSize = this.todos.size;
    for (const [id, todo] of this.todos.entries()) {
      if (todo.completed) {
        this.todos.delete(id);
      }
    }
    return beforeSize - this.todos.size;
  }
}

export const store = new Store();
