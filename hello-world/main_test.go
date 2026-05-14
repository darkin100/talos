package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func newTestServer() http.Handler {
	s := newStore()
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", handleHealth)
	mux.Handle("/todos", handleTodos(s))
	mux.Handle("/todos/", handleTodos(s))
	return mux
}

func TestHealth(t *testing.T) {
	srv := newTestServer()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
}

func TestCreateAndListTodo(t *testing.T) {
	srv := newTestServer()

	// Create
	body := strings.NewReader(`{"title":"write talk"}`)
	req := httptest.NewRequest(http.MethodPost, "/todos", body)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create: expected 201, got %d", rec.Code)
	}

	var created Todo
	if err := json.NewDecoder(rec.Body).Decode(&created); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if created.Title != "write talk" {
		t.Fatalf("expected title 'write talk', got %q", created.Title)
	}

	// List
	req = httptest.NewRequest(http.MethodGet, "/todos", nil)
	rec = httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("list: expected 200, got %d", rec.Code)
	}

	var list []Todo
	if err := json.NewDecoder(rec.Body).Decode(&list); err != nil {
		t.Fatalf("decode list: %v", err)
	}
	if len(list) != 1 {
		t.Fatalf("expected 1 todo, got %d", len(list))
	}
}

func TestUpdateAndDeleteTodo(t *testing.T) {
	srv := newTestServer()

	// Create
	req := httptest.NewRequest(http.MethodPost, "/todos", strings.NewReader(`{"title":"draft"}`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	var created Todo
	_ = json.NewDecoder(rec.Body).Decode(&created)

	// Update
	upd := map[string]any{"title": "draft v2", "completed": true}
	buf := &bytes.Buffer{}
	_ = json.NewEncoder(buf).Encode(upd)
	req = httptest.NewRequest(http.MethodPut, "/todos/"+itoa(created.ID), buf)
	rec = httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("update: expected 200, got %d", rec.Code)
	}

	// Delete
	req = httptest.NewRequest(http.MethodDelete, "/todos/"+itoa(created.ID), nil)
	rec = httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusNoContent {
		t.Fatalf("delete: expected 204, got %d", rec.Code)
	}
}

func TestBadRequests(t *testing.T) {
	srv := newTestServer()

	// Missing title
	req := httptest.NewRequest(http.MethodPost, "/todos", strings.NewReader(`{}`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for missing title, got %d", rec.Code)
	}

	// Invalid id
	req = httptest.NewRequest(http.MethodGet, "/todos/not-a-number", nil)
	rec = httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for bad id, got %d", rec.Code)
	}

	// Not found
	req = httptest.NewRequest(http.MethodGet, "/todos/999", nil)
	rec = httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", rec.Code)
	}
}

// itoa avoids pulling strconv into the test imports unnecessarily.
func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	var b [20]byte
	pos := len(b)
	for i > 0 {
		pos--
		b[pos] = byte('0' + i%10)
		i /= 10
	}
	return string(b[pos:])
}
