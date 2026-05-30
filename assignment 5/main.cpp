#include <iostream>
#include <climits>
#include <vector>
#include <functional>

// B-Tree Index Implementation
// Minimum degree t: every node (except root) has at least t-1 keys and at most 2t-1 keys.
// Root may have as few as 1 key.
// An internal node with k keys has k+1 children.

template <typename Key, typename Row>
class DB {
private:
  struct Entry {
    Key key;
    Row row;
  };

  struct BTree {
    std::vector<Entry> keys;
    std::vector<BTree *> children;
    bool leaf;

    BTree(bool isLeaf = true) : leaf(isLeaf) {}
  };

  BTree *root;
  size_t minDegree; // t — minimum degree
  size_t maxKeys;   // 2t - 1
  size_t minKeys;   // t - 1

  // ─── Helper: check if a node is full ───
  bool isFull(BTree *node) {
    return node->keys.size() == maxKeys;
  }

  // ─── Split child y = node->children[i] which is full ───
  // After split, node gets one more key and one more child.
  void splitChild(BTree *node, size_t i) {
    BTree *y = node->children[i];
    BTree *z = new BTree(y->leaf);

    // z gets the last (t-1) keys of y
    for (size_t j = 0; j < minDegree - 1; j++) {
      z->keys.push_back(y->keys[minDegree + j]);
    }
    // z gets the last t children of y (if y is internal)
    if (!y->leaf) {
      for (size_t j = 0; j < minDegree; j++) {
        z->children.push_back(y->children[minDegree + j]);
      }
    }

    // The median key moves up into the parent node
    Entry median = y->keys[minDegree - 1];

    // Shrink y to keep only first (t-1) keys
    y->keys.resize(minDegree - 1);
    if (!y->leaf) {
      y->children.resize(minDegree);
    }

    // Insert z as a child of node right after y
    node->children.insert(node->children.begin() + i + 1, z);
    // Insert median key into node at position i
    node->keys.insert(node->keys.begin() + i, median);
  }

  // ─── Insert into a non-full node ───
  void insertNonFull(BTree *node, Key key, Row row) {
    int i = (int)node->keys.size() - 1;

    if (node->leaf) {
      // Find position and insert
      node->keys.push_back(Entry{key, row}); // make room
      while (i >= 0 && key < node->keys[i].key) {
        node->keys[i + 1] = node->keys[i];
        i--;
      }
      node->keys[i + 1] = Entry{key, row};
    } else {
      // Find the child to descend into
      while (i >= 0 && key < node->keys[i].key) {
        i--;
      }
      i++;
      // If that child is full, split it first
      if (isFull(node->children[i])) {
        splitChild(node, i);
        // After split, median is at node->keys[i]
        if (key > node->keys[i].key) {
          i++;
        }
      }
      insertNonFull(node->children[i], key, row);
    }
  }

  // ─── Recursive search ───
  Entry *searchRecursive(Key key, BTree *node) {
    if (node == nullptr)
      return nullptr;

    size_t i = 0;
    // Find the first key >= search key
    while (i < node->keys.size() && key > node->keys[i].key) {
      i++;
    }

    // If we found an exact match
    if (i < node->keys.size() && node->keys[i].key == key) {
      return &(node->keys[i]);
    }

    // If this is a leaf, key is not in the tree
    if (node->leaf) {
      return nullptr;
    }

    // Recurse into the appropriate child
    return searchRecursive(key, node->children[i]);
  }

  // ─── In-order traversal ───
  void inorderTraversal(BTree *node, std::function<void(const Entry &)> visit) {
    if (node == nullptr)
      return;
    for (size_t i = 0; i < node->keys.size(); i++) {
      if (!node->leaf) {
        inorderTraversal(node->children[i], visit);
      }
      visit(node->keys[i]);
    }
    if (!node->leaf) {
      inorderTraversal(node->children[node->keys.size()], visit);
    }
  }

  // ─── Find predecessor (rightmost key in left subtree) ───
  Entry getPredecessor(BTree *node) {
    while (!node->leaf) {
      node = node->children[node->children.size() - 1];
    }
    return node->keys[node->keys.size() - 1];
  }

  // ─── Find successor (leftmost key in right subtree) ───
  Entry getSuccessor(BTree *node) {
    while (!node->leaf) {
      node = node->children[0];
    }
    return node->keys[0];
  }

  // ─── Ensure children[idx] has at least t keys (fill if it has t-1) ───
  void fill(BTree *node, size_t idx) {
    // Try borrowing from left sibling
    if (idx > 0 && node->children[idx - 1]->keys.size() >= minDegree) {
      borrowFromPrev(node, idx);
    }
    // Try borrowing from right sibling
    else if (idx < node->children.size() - 1 &&
             node->children[idx + 1]->keys.size() >= minDegree) {
      borrowFromNext(node, idx);
    }
    // Merge with a sibling
    else {
      if (idx < node->children.size() - 1) {
        merge(node, idx); // merge children[idx] and children[idx+1]
      } else {
        merge(node, idx - 1); // merge children[idx-1] and children[idx]
      }
    }
  }

  // ─── Borrow a key from children[idx-1] via parent ───
  void borrowFromPrev(BTree *node, size_t idx) {
    BTree *child = node->children[idx];
    BTree *sibling = node->children[idx - 1];

    // Shift all keys in child one step right
    child->keys.insert(child->keys.begin(), node->keys[idx - 1]);

    // If child is internal, move sibling's last child to child's front
    if (!child->leaf) {
      child->children.insert(child->children.begin(),
                             sibling->children[sibling->children.size() - 1]);
      sibling->children.pop_back();
    }

    // Move sibling's last key up to parent
    node->keys[idx - 1] = sibling->keys[sibling->keys.size() - 1];
    sibling->keys.pop_back();
  }

  // ─── Borrow a key from children[idx+1] via parent ───
  void borrowFromNext(BTree *node, size_t idx) {
    BTree *child = node->children[idx];
    BTree *sibling = node->children[idx + 1];

    // Take parent's key[idx] and append to child
    child->keys.push_back(node->keys[idx]);

    // If child is internal, move sibling's first child to child's end
    if (!child->leaf) {
      child->children.push_back(sibling->children[0]);
      sibling->children.erase(sibling->children.begin());
    }

    // Move sibling's first key up to parent
    node->keys[idx] = sibling->keys[0];
    sibling->keys.erase(sibling->keys.begin());
  }

  // ─── Merge children[idx] and children[idx+1] ───
  void merge(BTree *node, size_t idx) {
    BTree *left = node->children[idx];
    BTree *right = node->children[idx + 1];

    // Pull the separating key from parent into left
    left->keys.push_back(node->keys[idx]);

    // Copy all keys from right to left
    for (auto &k : right->keys) {
      left->keys.push_back(k);
    }

    // Copy all children from right to left
    if (!left->leaf) {
      for (auto *c : right->children) {
        left->children.push_back(c);
      }
    }

    // Remove the separator key and right pointer from parent
    node->keys.erase(node->keys.begin() + idx);
    node->children.erase(node->children.begin() + idx + 1);

    delete right;
  }

  // ─── Recursive delete ───
  void deleteRecursive(BTree *node, Key key) {
    size_t idx = 0;
    while (idx < node->keys.size() && key > node->keys[idx].key) {
      idx++;
    }

    // CASE 1: Key is in this node
    if (idx < node->keys.size() && node->keys[idx].key == key) {
      if (node->leaf) {
        // Case 1a: Key is in a leaf — simply remove it
        node->keys.erase(node->keys.begin() + idx);
      } else {
        // Case 1b: Key is in an internal node
        if (node->children[idx]->keys.size() >= minDegree) {
          // Replace with predecessor
          Entry pred = getPredecessor(node->children[idx]);
          node->keys[idx] = pred;
          deleteRecursive(node->children[idx], pred.key);
        } else if (node->children[idx + 1]->keys.size() >= minDegree) {
          // Replace with successor
          Entry succ = getSuccessor(node->children[idx + 1]);
          node->keys[idx] = succ;
          deleteRecursive(node->children[idx + 1], succ.key);
        } else {
          // Both children have t-1 keys — merge and recurse
          merge(node, idx);
          deleteRecursive(node->children[idx], key);
        }
      }
    }
    // CASE 2: Key is not in this node, descend
    else {
      if (node->leaf) {
        std::cout << "Key " << key << " not found in tree.\n";
        return;
      }

      bool lastChild = (idx == node->keys.size());

      // If the child we need to descend into has only t-1 keys, fill it
      if (node->children[idx]->keys.size() < minDegree) {
        fill(node, idx);
      }

      // After fill, idx might have changed (if we merged with left sibling)
      if (lastChild && idx > node->keys.size()) {
        deleteRecursive(node->children[idx - 1], key);
      } else {
        deleteRecursive(node->children[idx], key);
      }
    }
  }

  // ─── Recursive cleanup ───
  void destroyTree(BTree *node) {
    if (node == nullptr)
      return;
    for (auto *child : node->children) {
      destroyTree(child);
    }
    delete node;
  }

public:
  DB(size_t degree) {
    minDegree = degree;
    maxKeys = 2 * degree - 1;
    minKeys = degree - 1;
    root = new BTree(true); // root starts as an empty leaf
  }

  ~DB() { destroyTree(root); }

  // ─── Search ───
  Entry *Search(Key key) { return searchRecursive(key, root); }

  // ─── Insert ───
  void Insert(Key key, Row row) {
    if (isFull(root)) {
      // Tree grows in height: create a new root
      BTree *newRoot = new BTree(false);
      newRoot->children.push_back(root);
      splitChild(newRoot, 0);
      root = newRoot;

      // Now insert into the (non-full) new tree
      insertNonFull(root, key, row);
    } else {
      insertNonFull(root, key, row);
    }
  }

  // ─── Delete ───
  void Delete(Key key) {
    if (root->keys.empty()) {
      std::cout << "Tree is empty.\n";
      return;
    }
    deleteRecursive(root, key);

    // If root has 0 keys and has a child, shrink the tree
    if (root->keys.empty() && !root->leaf) {
      BTree *oldRoot = root;
      root = root->children[0];
      oldRoot->children.clear();
      delete oldRoot;
    }
  }

  // ─── Print in-order ───
  void Print() {
    inorderTraversal(root, [](const Entry &e) {
      std::cout << "[" << e.key << ": " << e.row << "] ";
    });
    std::cout << "\n";
  }

  // ─── Print tree structure (level-by-level for debugging) ───
  void PrintTree() {
    printNode(root, 0);
  }

private:
  void printNode(BTree *node, int level) {
    if (node == nullptr)
      return;
    std::string indent(level * 4, ' ');
    std::cout << indent << "[ ";
    for (size_t i = 0; i < node->keys.size(); i++) {
      if (i > 0)
        std::cout << " | ";
      std::cout << node->keys[i].key;
    }
    std::cout << " ]" << (node->leaf ? " (leaf)" : "") << "\n";
    for (auto *child : node->children) {
      printNode(child, level + 1);
    }
  }
};

// ─── Main: Demo Driver ───
int main() {
  std::cout << "===== B-Tree Index Demo (minDegree = 3) =====\n\n";

  // Create a B-Tree of minimum degree 3 (each node holds 2..5 keys)
  // Key = int, Row = std::string
  DB<int, std::string> db(3);

  // Insert entries
  int insertKeys[] = {10, 20, 5, 6, 12, 30, 7, 17, 3, 1, 25, 40, 35, 50, 15};
  for (int k : insertKeys) {
    std::cout << "Insert " << k << "\n";
    db.Insert(k, "ROW_OF_" + std::to_string(k));
  }

  std::cout << "\n--- In-order traversal after insertions ---\n";
  db.Print();

  std::cout << "\n--- Tree structure ---\n";
  db.PrintTree();

  // Search
  std::cout << "\n--- Search ---\n";
  int searchKeys[] = {6, 15, 99};
  for (int k : searchKeys) {
    auto *result = db.Search(k);
    if (result) {
      std::cout << "Search(" << k << ") => FOUND: [" << result->key << ": "
                << result->row << "]\n";
    } else {
      std::cout << "Search(" << k << ") => NOT FOUND\n";
    }
  }

  // Delete
  std::cout << "\n--- Deletions ---\n";
  int deleteKeys[] = {6, 30, 10, 50};
  for (int k : deleteKeys) {
    std::cout << "Delete " << k << "\n";
    db.Delete(k);
    std::cout << "  After delete: ";
    db.Print();
  }

  std::cout << "\n--- Final tree structure ---\n";
  db.PrintTree();

  return 0;
}