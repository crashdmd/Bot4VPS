import { esc } from './api.js';
import { serviceProjects } from './service-projects-data.js?v=20261123-project-info';

export function renderProjectInfo(container, id) {
  const project = serviceProjects.find(row => row.id === id);
  if (!container || !project) return;
  const owner = project.repository.split('/')[0];
  container.innerHTML = `<article class="upstream-project" aria-label="О проекте ${esc(project.name)}">
    <p>${esc(project.description)}</p>
    <div class="upstream-project-links">
      <span><a href="https://github.com/${esc(owner)}" target="_blank" rel="noopener noreferrer">${esc(project.author)}</a></span><span aria-hidden="true">·</span>
      <a href="https://github.com/${esc(project.repository)}" target="_blank" rel="noopener noreferrer">GitHub ↗</a>
    </div>
  </article>`;
}
