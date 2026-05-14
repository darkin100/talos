// Package main implements a simple in-memory Todo API for the Talos
// agentified SDLC demonstration. It emits structured JSON logs to stdout
// so that downstream observability (Arize Phoenix) can ingest them.
package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Todo represents a single todo item.
type Todo struct {
	ID        int       `json:"id"`
	Title     string    `json:"title"`
	Completed bool      `json:"completed"`
	CreatedAt time.Time `json:"created_at"`
}

// store is a thread-safe in-memory todo collection.
type store struct {
	mu     sync.RWMutex
	todos  map[int]Todo
	nextID int
}

func newStore() *store {
	return &store{todos: make(map[int]Todo), nextID: 1}
}

func (s *store) list() []Todo {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Todo, 0, len(s.todos))
	for _, t := range s.todos {
		out = append(out, t)
	}
	return out
}

func (s *store) get(id int) (Todo, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	t, ok := s.todos[id]
	return t, ok
}

func (s *store) create(title string) Todo {
	s.mu.Lock()
	defer s.mu.Unlock()
	t := Todo{ID: s.nextID, Title: title, CreatedAt: time.Now().UTC()}
	s.todos[s.nextID] = t
	s.nextID++
	return t
}

func (s *store) update(id int, title string, completed bool) (Todo, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	t, ok := s.todos[id]
	if !ok {
		return Todo{}, false
	}
	t.Title = title
	t.Completed = completed
	s.todos[id] = t
	return t, true
}

func (s *store) delete(id int) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.todos[id]; !ok {
		return false
	}
	delete(s.todos, id)
	return true
}

// logEvent emits a single-line JSON log so Phoenix/log aggregators can parse it.
func logEvent(level, msg string, fields map[string]any) {
	entry := map[string]any{
		"timestamp": time.Now().UTC().Format(time.RFC3339Nano),
		"level":     level,
		"message":   msg,
		"service":   "todo-api",
	}
	for k, v := range fields {
		entry[k] = v
	}
	b, _ := json.Marshal(entry)
	fmt.Fprintln(os.Stdout, string(b))
}

// loggingMiddleware records request/response metadata as structured logs.
func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r)
		logEvent("info", "http_request", map[string]any{
			"method":      r.Method,
			"path":        r.URL.Path,
			"status":      rec.status,
			"duration_ms": time.Since(start).Milliseconds(),
		})
	})
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	logEvent("error", msg, map[string]any{"status": status})
	writeJSON(w, status, map[string]string{"error": msg})
}

// handleTodos routes /todos and /todos/{id} requests to the store.
func handleTodos(s *store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/todos")
		path = strings.TrimPrefix(path, "/")

		if path == "" {
			switch r.Method {
			case http.MethodGet:
				writeJSON(w, http.StatusOK, s.list())
			case http.MethodPost:
				var body struct {
					Title string `json:"title"`
				}
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Title == "" {
					writeError(w, http.StatusBadRequest, "title is required")
					return
				}
				writeJSON(w, http.StatusCreated, s.create(body.Title))
			default:
				writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			}
			return
		}

		id, err := strconv.Atoi(path)
		if err != nil {
			writeError(w, http.StatusBadRequest, "invalid todo id")
			return
		}

		switch r.Method {
		case http.MethodGet:
			t, ok := s.get(id)
			if !ok {
				writeError(w, http.StatusNotFound, "todo not found")
				return
			}
			writeJSON(w, http.StatusOK, t)
		case http.MethodPut:
			var body struct {
				Title     string `json:"title"`
				Completed bool   `json:"completed"`
			}
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				writeError(w, http.StatusBadRequest, "invalid body")
				return
			}
			t, ok := s.update(id, body.Title, body.Completed)
			if !ok {
				writeError(w, http.StatusNotFound, "todo not found")
				return
			}
			writeJSON(w, http.StatusOK, t)
		case http.MethodDelete:
			if !s.delete(id) {
				writeError(w, http.StatusNotFound, "todo not found")
				return
			}
			w.WriteHeader(http.StatusNoContent)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
	}
}

func handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	s := newStore()
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", handleHealth)
	mux.Handle("/todos", handleTodos(s))
	mux.Handle("/todos/", handleTodos(s))

	srv := &http.Server{
		Addr:              ":" + port,
		Handler:           loggingMiddleware(mux),
		ReadHeaderTimeout: 5 * time.Second,
	}

	logEvent("info", "server_starting", map[string]any{"port": port})
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("server failed: %v", err)
	}
}
