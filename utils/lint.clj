(require '[clojure.data.csv :as csv]
         '[clojure.java.io :as io]
         '[babashka.cli :as cli]
         '[clojure.string :as str])

(def cli-options {:files {}})

(def opts (cli/parse-opts *command-line-args* {:coerce {:files [] }}))

(defn output-notice-fix [line file]
  [{:type "::notice" :file file :msg "Missing EOL was fixed for you" :col 1 :line line}])

(defn fix-eol-at-eof! [lines file]
  (when (false? (str/ends-with? (slurp file) "\n"))
    (spit file "\n" :append true)
    (output-notice-fix (count lines) file)))

(defn output-error-fields [lines file]
  (let [n (count (first lines))]
    (->> lines
         (keep-indexed #(when (not= n (count %2)) %1))
         (map (fn [idx] {:type "::error" :file file :msg (str "Number of fields is not " n) :col 1 :line (inc idx) })))))

(defn lint [rows file]
  (concat (output-error-fields rows file) (fix-eol-at-eof! rows file)))

(defn gh-workflow-format [coll]
  (map #(str (% :type) " file=" (% :file) ",line=" (% :line) ",col=" (% :col) "::" (% :msg)) coll))

(defn gh-workflow-print [msg]
  (when (seq msg)
    (println (first msg))
    (recur (rest msg))))

(doseq [file (opts :files)]
  (println (str "Processing " file))
  (let [rows (with-open [reader (io/reader file)] (doall (csv/read-csv reader)))]
    (->>
     (lint rows file)
     (gh-workflow-format)
     (gh-workflow-print))))
