// EasyMDE Markdown 编辑器初始化
// 依赖页面中已注入的 csrfToken 变量，以及 marked、katex、renderMathInElement

function uploadImageFile(file, csrfToken) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('csrf_token', csrfToken);

    return fetch('/admin/upload', {
        method: 'POST',
        body: formData
    })
        .then(function (res) {
            return res.json().then(function (data) {
                if (!res.ok) {
                    throw new Error(data.detail || '上传失败');
                }
                return data;
            });
        })
        .then(function (data) {
            if (!data.url) {
                throw new Error('上传失败');
            }
            return data.url;
        });
}

function initEditor(textareaId, csrfToken) {
    const editor = new EasyMDE({
        element: document.getElementById(textareaId),
        spellChecker: false,
        autosave: { enabled: true, uniqueId: 'post-editor' },
        status: ['autosave', 'lines', 'words', 'cursor'],
        toolbar: [
            'bold', 'italic', 'heading', '|',
            'quote', 'unordered-list', 'ordered-list', '|',
            'link', 'image', 'table', 'code', '|',
            'preview', 'fullscreen', '|',
            'guide'
        ],
        uploadImage: true,
        imageUploadFunction: function (file, onSuccess, onError) {
            uploadImageFile(file, csrfToken)
                .then(onSuccess)
                .catch(function (err) {
                    onError(err.message || '上传失败');
                });
        },
        previewRender: function (plainText) {
            return renderMarkdownPreview(plainText);
        }
    });

    return editor;
}

function renderMarkdownPreview(plainText) {
    const html = window.marked ? window.marked.parse(plainText) : plainText;
    const temp = document.createElement('div');
    temp.innerHTML = html;
    if (window.renderMathInElement) {
        window.renderMathInElement(temp, {
            delimiters: [
                { left: '$$', right: '$$', display: true },
                { left: '$', right: '$', display: false }
            ],
            throwOnError: false
        });
    }
    return temp.innerHTML;
}

function initInlinePreview(editor, previewId) {
    const preview = document.getElementById(previewId);
    if (!preview || !editor) return;

    function updatePreview() {
        preview.innerHTML = renderMarkdownPreview(editor.value());
    }

    editor.codemirror.on('change', updatePreview);
    updatePreview();
}

function initTextareaPreview(textareaId, previewId) {
    const textarea = document.getElementById(textareaId);
    const preview = document.getElementById(previewId);
    if (!textarea || !preview) return;

    function updatePreview() {
        preview.innerHTML = renderMarkdownPreview(textarea.value);
    }

    textarea.addEventListener('input', updatePreview);
    updatePreview();
}

function initImageUrlUpload(fileInputId, urlInputId, previewId, csrfToken) {
    const fileInput = document.getElementById(fileInputId);
    const urlInput = document.getElementById(urlInputId);
    const preview = document.getElementById(previewId);
    if (!fileInput || !urlInput || !preview) return;

    const button = fileInput.closest('.upload-btn');
    const defaultText = button ? button.childNodes[0].textContent.trim() : '';

    function syncPreview() {
        const url = urlInput.value.trim();
        preview.src = url;
        preview.style.display = url ? 'block' : 'none';
    }

    syncPreview();
    urlInput.addEventListener('input', syncPreview);
    fileInput.addEventListener('change', function () {
        const file = fileInput.files && fileInput.files[0];
        if (!file) return;

        if (button) {
            button.childNodes[0].textContent = '上传中...';
            button.classList.add('is-loading');
        }

        uploadImageFile(file, csrfToken)
            .then(function (url) {
                urlInput.value = url;
                syncPreview();
            })
            .catch(function (err) {
                alert(err.message || '上传失败');
            })
            .finally(function () {
                fileInput.value = '';
                if (button) {
                    button.childNodes[0].textContent = defaultText || '上传图片';
                    button.classList.remove('is-loading');
                }
            });
    });
}

function initCoverUpload(fileInputId, urlInputId, previewId, csrfToken) {
    initImageUrlUpload(fileInputId, urlInputId, previewId, csrfToken);
}

function initContentImageUpload(fileInputId, editor, csrfToken) {
    const fileInput = document.getElementById(fileInputId);
    if (!fileInput || !editor) return;

    const button = fileInput.closest('.upload-btn');
    const defaultText = button ? button.childNodes[0].textContent.trim() : '';

    fileInput.addEventListener('change', function () {
        const file = fileInput.files && fileInput.files[0];
        if (!file) return;

        if (button) {
            button.childNodes[0].textContent = '上传中...';
            button.classList.add('is-loading');
        }

        uploadImageFile(file, csrfToken)
            .then(function (url) {
                const alt = file.name.replace(/\.[^.]+$/, '') || '图片';
                const cm = editor.codemirror;
                const imageMarkdown = `![${alt}](${url})`;
                cm.replaceSelection(imageMarkdown);
                cm.focus();
            })
            .catch(function (err) {
                alert(err.message || '上传失败');
            })
            .finally(function () {
                fileInput.value = '';
                if (button) {
                    button.childNodes[0].textContent = defaultText || '上传正文图片';
                    button.classList.remove('is-loading');
                }
            });
    });
}
