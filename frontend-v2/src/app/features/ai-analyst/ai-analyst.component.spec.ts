import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AiAnalystComponent } from './ai-analyst.component';

describe('AiAnalystComponent', () => {
  let component: AiAnalystComponent;
  let fixture: ComponentFixture<AiAnalystComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AiAnalystComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(AiAnalystComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
