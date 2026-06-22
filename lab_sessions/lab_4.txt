# Lab Session 4: Red-Black Tree & Full B-Tree in C++

## Objective
Implement a Red-Black Tree (self-balancing BST used in database index structures) and a full B-Tree (the actual on-disk index structure used by PostgreSQL, MySQL, SQLite) supporting insert, merge (split promotion), and delete with underflow merging.

---

# Part 1: Red-Black Tree

## Properties
1. Every node is Red or Black.
2. Root is Black.
3. No two consecutive Red nodes (Red node's parent must be Black).
4. Every path from a node to its NULL descendants has the same number of Black nodes.

These invariants guarantee O(log n) height.

## Implementation

```cpp
#include <iostream>

enum Color { RED, BLACK };

struct RBNode {
    int     key;
    Color   color;
    RBNode *left, *right, *parent;

    explicit RBNode(int k)
        : key(k), color(RED), left(nullptr), right(nullptr), parent(nullptr) {}
};

class RedBlackTree {
    RBNode* root = nullptr;

    void left_rotate(RBNode* x) {
        RBNode* y = x->right;
        x->right = y->left;
        if (y->left) y->left->parent = x;
        y->parent = x->parent;
        if (!x->parent)       root = y;
        else if (x == x->parent->left) x->parent->left  = y;
        else                           x->parent->right = y;
        y->left = x;
        x->parent = y;
    }

    void right_rotate(RBNode* x) {
        RBNode* y = x->left;
        x->left = y->right;
        if (y->right) y->right->parent = x;
        y->parent = x->parent;
        if (!x->parent)       root = y;
        else if (x == x->parent->right) x->parent->right = y;
        else                            x->parent->left  = y;
        y->right = x;
        x->parent = y;
    }

    void fix_insert(RBNode* z) {
        while (z->parent && z->parent->color == RED) {
            RBNode* gp = z->parent->parent;
            if (z->parent == gp->left) {
                RBNode* uncle = gp->right;
                if (uncle && uncle->color == RED) {         // Case 1: recolor
                    z->parent->color = BLACK;
                    uncle->color     = BLACK;
                    gp->color        = RED;
                    z = gp;
                } else {
                    if (z == z->parent->right) {            // Case 2: left-rotate parent
                        z = z->parent;
                        left_rotate(z);
                    }
                    z->parent->color = BLACK;               // Case 3: right-rotate grandparent
                    gp->color        = RED;
                    right_rotate(gp);
                }
            } else {                                        // Mirror cases
                RBNode* uncle = gp->left;
                if (uncle && uncle->color == RED) {
                    z->parent->color = BLACK;
                    uncle->color     = BLACK;
                    gp->color        = RED;
                    z = gp;
                } else {
                    if (z == z->parent->left) {
                        z = z->parent;
                        right_rotate(z);
                    }
                    z->parent->color = BLACK;
                    gp->color        = RED;
                    left_rotate(gp);
                }
            }
        }
        root->color = BLACK;
    }

    void transplant(RBNode* u, RBNode* v) {
        if (!u->parent)           root = v;
        else if (u == u->parent->left) u->parent->left  = v;
        else                           u->parent->right = v;
        if (v) v->parent = u->parent;
    }

    RBNode* minimum(RBNode* node) {
        while (node->left) node = node->left;
        return node;
    }

    void fix_delete(RBNode* x, RBNode* x_parent) {
        while (x != root && (!x || x->color == BLACK)) {
            if (x == (x_parent ? x_parent->left : nullptr)) {
                RBNode* w = x_parent->right;
                if (w && w->color == RED) {
                    w->color        = BLACK;
                    x_parent->color = RED;
                    left_rotate(x_parent);
                    w = x_parent->right;
                }
                if ((!w->left || w->left->color == BLACK) &&
                    (!w->right || w->right->color == BLACK)) {
                    if (w) w->color = RED;
                    x = x_parent; x_parent = x->parent;
                } else {
                    if (!w->right || w->right->color == BLACK) {
                        if (w->left) w->left->color = BLACK;
                        w->color = RED;
                        right_rotate(w);
                        w = x_parent->right;
                    }
                    w->color = x_parent->color;
                    x_parent->color = BLACK;
                    if (w->right) w->right->color = BLACK;
                    left_rotate(x_parent);
                    x = root;
                }
            } else {
                RBNode* w = x_parent->left;
                if (w && w->color == RED) {
                    w->color        = BLACK;
                    x_parent->color = RED;
                    right_rotate(x_parent);
                    w = x_parent->left;
                }
                if ((!w->right || w->right->color == BLACK) &&
                    (!w->left  || w->left->color  == BLACK)) {
                    if (w) w->color = RED;
                    x = x_parent; x_parent = x->parent;
                } else {
                    if (!w->left || w->left->color == BLACK) {
                        if (w->right) w->right->color = BLACK;
                        w->color = RED;
                        left_rotate(w);
                        w = x_parent->left;
                    }
                    w->color = x_parent->color;
                    x_parent->color = BLACK;
                    if (w->left) w->left->color = BLACK;
                    right_rotate(x_parent);
                    x = root;
                }
            }
        }
        if (x) x->color = BLACK;
    }

    void inorder(RBNode* node) const {
        if (!node) return;
        inorder(node->left);
        std::cout << node->key << (node->color == RED ? "R" : "B") << " ";
        inorder(node->right);
    }

public:
    void insert(int key) {
        RBNode* z = new RBNode(key);
        RBNode* y = nullptr;
        RBNode* x = root;
        while (x) {
            y = x;
            x = (z->key < x->key) ? x->left : x->right;
        }
        z->parent = y;
        if (!y)                  root = z;
        else if (z->key < y->key) y->left  = z;
        else                       y->right = z;
        fix_insert(z);
    }

    void remove(int key) {
        RBNode* z = root;
        while (z && z->key != key)
            z = (key < z->key) ? z->left : z->right;
        if (!z) return;

        RBNode* y = z;
        RBNode* x = nullptr;
        RBNode* x_parent = nullptr;
        Color   y_orig_color = y->color;

        if (!z->left) {
            x = z->right; x_parent = z->parent;
            transplant(z, z->right);
        } else if (!z->right) {
            x = z->left; x_parent = z->parent;
            transplant(z, z->left);
        } else {
            y = minimum(z->right);
            y_orig_color = y->color;
            x = y->right;
            if (y->parent == z) { x_parent = y; }
            else {
                x_parent = y->parent;
                transplant(y, y->right);
                y->right = z->right;
                y->right->parent = y;
            }
            transplant(z, y);
            y->left = z->left; y->left->parent = y;
            y->color = z->color;
        }
        delete z;
        if (y_orig_color == BLACK) fix_delete(x, x_parent);
    }

    void print() const { inorder(root); std::cout << "\n"; }
};

int main() {
    RedBlackTree rbt;
    for (int k : {10, 20, 30, 15, 25, 5, 1})
        rbt.insert(k);

    std::cout << "Inorder (key + color R/B):\n";
    rbt.print();

    rbt.remove(20);
    std::cout << "After removing 20:\n";
    rbt.print();
}
```

```bash
g++ -std=c++17 -o rbt rbt.cpp && ./rbt
```

---

# Part 2: Full B-Tree (order t)

Every internal node holds between `t-1` and `2t-1` keys, and has between `t` and `2t` children. A leaf holds `t-1` to `2t-1` keys. Root may hold as few as 1 key.

Supported operations: **insert** (split on the way down), **search**, **delete** (merge / borrow on the way down).

```cpp
#include <iostream>
#include <vector>

const int T = 2;   // minimum degree; change to increase fanout

struct BNode {
    std::vector<int>    keys;
    std::vector<BNode*> children;
    bool                leaf = true;

    BNode() = default;
};

class BTree {
    BNode* root = nullptr;

    // Split child[i] of parent (child must be full: 2T-1 keys)
    void split_child(BNode* parent, int i) {
        BNode* y = parent->children[i];
        BNode* z = new BNode();
        z->leaf  = y->leaf;

        // z gets the right half of y's keys
        z->keys.assign(y->keys.begin() + T, y->keys.end());
        y->keys.resize(T - 1);

        if (!y->leaf) {
            z->children.assign(y->children.begin() + T, y->children.end());
            y->children.resize(T);
        }

        // Promote median key to parent
        int median = z->keys.front();   // was y->keys[T-1] before resize... hold it
        // Redo: median is y->keys[T-1] before we erase it
        // Correct split:
        z->keys.clear();
        z->keys.assign(y->keys.begin() + T, y->keys.end());
        int med = y->keys[T - 1];
        y->keys.resize(T - 1);
        if (!y->leaf) {
            z->children.assign(y->children.begin() + T, y->children.end());
            y->children.resize(T);
        }

        parent->keys.insert(parent->keys.begin() + i, med);
        parent->children.insert(parent->children.begin() + i + 1, z);
    }

    void insert_non_full(BNode* node, int key) {
        int i = (int)node->keys.size() - 1;
        if (node->leaf) {
            node->keys.push_back(0);
            while (i >= 0 && key < node->keys[i]) {
                node->keys[i + 1] = node->keys[i];
                i--;
            }
            node->keys[i + 1] = key;
        } else {
            while (i >= 0 && key < node->keys[i]) i--;
            i++;
            if ((int)node->children[i]->keys.size() == 2 * T - 1) {
                split_child(node, i);
                if (key > node->keys[i]) i++;
            }
            insert_non_full(node->children[i], key);
        }
    }

    // Find predecessor (largest key in left subtree of keys[idx])
    int get_predecessor(BNode* node, int idx) {
        BNode* cur = node->children[idx];
        while (!cur->leaf) cur = cur->children.back();
        return cur->keys.back();
    }

    // Find successor (smallest key in right subtree of keys[idx])
    int get_successor(BNode* node, int idx) {
        BNode* cur = node->children[idx + 1];
        while (!cur->leaf) cur = cur->children.front();
        return cur->keys.front();
    }

    // Merge children[idx] and children[idx+1] around keys[idx]
    void merge(BNode* node, int idx) {
        BNode* left  = node->children[idx];
        BNode* right = node->children[idx + 1];

        left->keys.push_back(node->keys[idx]);
        left->keys.insert(left->keys.end(), right->keys.begin(), right->keys.end());
        if (!left->leaf)
            left->children.insert(left->children.end(),
                                  right->children.begin(), right->children.end());

        node->keys.erase(node->keys.begin() + idx);
        node->children.erase(node->children.begin() + idx + 1);
        delete right;
    }

    // Ensure child[idx] has at least T keys before descending
    void fill(BNode* node, int idx) {
        if (idx > 0 && (int)node->children[idx-1]->keys.size() >= T) {
            // Borrow from left sibling
            BNode* child  = node->children[idx];
            BNode* sibling= node->children[idx - 1];
            child->keys.insert(child->keys.begin(), node->keys[idx - 1]);
            node->keys[idx - 1] = sibling->keys.back();
            sibling->keys.pop_back();
            if (!child->leaf) {
                child->children.insert(child->children.begin(), sibling->children.back());
                sibling->children.pop_back();
            }
        } else if (idx < (int)node->children.size()-1 &&
                   (int)node->children[idx+1]->keys.size() >= T) {
            // Borrow from right sibling
            BNode* child  = node->children[idx];
            BNode* sibling= node->children[idx + 1];
            child->keys.push_back(node->keys[idx]);
            node->keys[idx] = sibling->keys.front();
            sibling->keys.erase(sibling->keys.begin());
            if (!child->leaf) {
                child->children.push_back(sibling->children.front());
                sibling->children.erase(sibling->children.begin());
            }
        } else {
            if (idx < (int)node->children.size() - 1) merge(node, idx);
            else                                        merge(node, idx - 1);
        }
    }

    void delete_key(BNode* node, int key) {
        int idx = 0;
        while (idx < (int)node->keys.size() && key > node->keys[idx]) idx++;

        if (idx < (int)node->keys.size() && node->keys[idx] == key) {
            // Key is in this node
            if (node->leaf) {
                node->keys.erase(node->keys.begin() + idx);
            } else if ((int)node->children[idx]->keys.size() >= T) {
                int pred = get_predecessor(node, idx);
                node->keys[idx] = pred;
                delete_key(node->children[idx], pred);
            } else if ((int)node->children[idx+1]->keys.size() >= T) {
                int succ = get_successor(node, idx);
                node->keys[idx] = succ;
                delete_key(node->children[idx+1], succ);
            } else {
                merge(node, idx);
                delete_key(node->children[idx], key);
            }
        } else {
            if (node->leaf) { std::cout << "Key not found\n"; return; }
            bool last = (idx == (int)node->children.size());
            if ((int)node->children[last ? idx-1 : idx]->keys.size() < T)
                fill(node, last ? idx-1 : idx);
            if (last && idx > (int)node->keys.size())
                delete_key(node->children[idx-1], key);
            else
                delete_key(node->children[idx], key);
        }
    }

    void inorder(BNode* node) const {
        if (!node) return;
        for (int i = 0; i < (int)node->keys.size(); i++) {
            if (!node->leaf) inorder(node->children[i]);
            std::cout << node->keys[i] << " ";
        }
        if (!node->leaf) inorder(node->children.back());
    }

public:
    void insert(int key) {
        if (!root) {
            root = new BNode();
            root->keys.push_back(key);
            return;
        }
        if ((int)root->keys.size() == 2 * T - 1) {
            BNode* s = new BNode();
            s->leaf = false;
            s->children.push_back(root);
            split_child(s, 0);
            root = s;
        }
        insert_non_full(root, key);
    }

    void remove(int key) {
        if (!root) return;
        delete_key(root, key);
        if (root->keys.empty() && !root->leaf) {
            BNode* old = root;
            root = root->children[0];
            delete old;
        }
    }

    bool search(BNode* node, int key) const {
        int i = 0;
        while (i < (int)node->keys.size() && key > node->keys[i]) i++;
        if (i < (int)node->keys.size() && node->keys[i] == key) return true;
        if (node->leaf) return false;
        return search(node->children[i], key);
    }

    bool search(int key) const { return root && search(root, key); }

    void print() const { inorder(root); std::cout << "\n"; }
};

int main() {
    BTree bt;
    for (int k : {10, 20, 5, 6, 12, 30, 7, 17, 3, 1, 25})
        bt.insert(k);

    std::cout << "Inorder after inserts:\n";
    bt.print();

    std::cout << "Search 17: " << (bt.search(17) ? "found" : "not found") << "\n";
    std::cout << "Search 99: " << (bt.search(99) ? "found" : "not found") << "\n";

    bt.remove(6);
    bt.remove(20);
    std::cout << "Inorder after removing 6 and 20:\n";
    bt.print();
}
```

```bash
g++ -std=c++17 -o btree btree.cpp && ./btree
```

---

## Red-Black Tree vs B-Tree — When to use which

| Property           | Red-Black Tree                        | B-Tree (order t)                          |
|--------------------|---------------------------------------|-------------------------------------------|
| Storage            | In-memory                             | Designed for disk (large node = 1 page)   |
| Node size          | 1 key per node                        | Up to `2t-1` keys per node                |
| Height             | O(log n)                              | O(log_t n) — much shorter for large t     |
| Use in databases   | In-memory indexes, std::map           | On-disk indexes (PostgreSQL, MySQL, InnoDB)|
| Cache friendliness | Poor (pointer chasing)                | Excellent (sequential keys in one node)   |
| Merge/split        | Rotation only                         | Child split / sibling borrow / merge      |

PostgreSQL's B-Tree index pages are 8 KB by default — matching `page_size` from Lab 2 — so one disk read fetches an entire B-Tree node.

---

## Key Takeaways
- Red-Black Trees maintain balance via color + rotation; ideal for in-memory sorted maps.
- B-Trees minimize disk I/O by packing many keys into one node = one page read.
- Delete in B-Trees has three cases: borrow from sibling, merge with sibling, or replace with predecessor/successor.
- The `T` (minimum degree) directly controls the fanout and tree height — higher T → shorter tree → fewer disk seeks.
