#include <iostream>

// [  [] 10|ROW_OF_10 [] 20|ROW_OF_20  [] 40|ROW_OF_40 []]
//    /
#include <climits>
#include <vector>
template <typename Key, typename Row> class DB {
private:
  struct Entry {
    Key key;
    Row row;
  };
  struct BTree {
    std::vector<Entry> keys;
    std::vector<BTree *> children;
  };

  BTree *root;
  size_t minDegree; // CHILDREN IN A HALF NODE
  size_t maxDegree; // CHILDREN IN A FULL NODE
  size_t minKeys;
  size_t maxKeys;


  bool isFull(BTree *root) {
    return root->children.size() == maxKeys;
  }
public:
  DB(size_t degree) {
    minDegree = degree;
    root = new BTree(minDegree);
  }

  Entry Search(Key key) {
    BTree* rootPtr = root;
    return SearchRecusive(key,root);
  }
  Entry SearchRecusive(Key key, BTree *rootPtr) {

    // BASE CONDITIPN
    if (rootPtr == nullptr)
      return Entry(-1);


    BTree* dummy = nullptr;
    for (size_t i=0;i<rootPtr->children.size();i++) {
      if (i < rootPtr->children.size()-1) {
        if (rootPtr->keys[i] == key) {
          return TRUE;
        }
      }
      int LRange, RRange;
      if (i == 0) {
        LRange = 0;
      }
      else {
        LRange = rootPtr->keys[i-1];
      }
      if (i == rootPtr->children.size()-1) {
        RRange = INT_MAX;
      }
      else {
        RRange = rootPtr->keys[i];
      }
      if (LRange <= key and RRange>=key) {
        dummy = rootPtr->children[i] ;
        break;
      }
    }
    // recursion
    SearchRecuesive(key, dummy);
  }
  void Insert(Key key, Row row) {
    BTree* rootPtr = root;

    if (isFull(rootPtr)) {
      /// SPLITTING AND STUFF
    }
    else {

      // SEARCH THE INDEX TO INSERT A KEY
      // NOW HOW TO SEARCH ???

      // 10 15 20 30
      // 15
      //keys.insert(1,15)
    }
  }
  

};

int main() {}